"""Reviews (post-trade critique) routes."""
import json
import math
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
from datetime import date
from app.database import get_db
from app.llm import call_llm, call_llm_stream
from app.feishu import send_review_notification, send_big_pnl_alert

router = APIRouter(prefix="/api/reviews", tags=["reviews"])

CRITIQUE_SYSTEM_PROMPT = """你是一个极端理性的交易心理教练。你的风格：
- 尖锐、直击要害，把交易员的行为和后果钉在一起让人无法逃避
- 用数据和逻辑说话，不用空洞的鼓励
- 如果交易员违背了自己的计划或交易纪律规则，你要精确指出哪条被违背了，以及这种行为模式的长期代价
- 如果交易员执行了计划但亏损，你要肯定纪律性，分析是否是概率正常波动
- 不使用侮辱性/攻击性词汇，但可以用反问、类比让人无处可逃
- 如果提供了情绪评分，分析情绪状态对交易决策的影响
- 回复控制在 300 字以内，每一句都要有信息量"""

INTENSITY_MODIFIERS = {
    "1": "\n\n注意：你的语气要温和、鼓励为主，像一个耐心的导师。指出问题但给予正面引导。",
    "2": "\n\n注意：你的语气要平和理性，客观分析，不需要太尖锐。",
    "3": "",  # default
    "4": "\n\n注意：你的语气要更加尖锐犀利，用反问和类比让交易员无处可逃。不留情面。",
    "5": "\n\n注意：你要用最极端毒舌的方式拷打交易员。每一句话都要像刀子一样扎心。用讽刺、反问、极端类比，让交易员痛到骨子里。但不要人身攻击。",
}

EXTRACT_WEAKNESS_PROMPT = """分析以下交易复盘对话，提取交易员暴露的心理弱点。
返回严格的 JSON 数组，每个元素包含：
- tag: 弱点标签（简短，如"报复性下单"、"扛单不止损"、"盈利后膨胀"）
- severity: 严重程度 0.1-1.0

只返回 JSON 数组，不要其他文字。如果没有明显弱点，返回空数组 []。"""


class ReviewCreate(BaseModel):
    trade_date: str | None = None
    pnl: float | None = None
    emotion_log: str
    mood: int | None = None  # 1-5 scale: 1=very bad, 5=very good

    @field_validator("emotion_log")
    @classmethod
    def emotion_length(cls, v):
        if len(v) > 5000:
            raise ValueError("内容不能超过 5000 字符")
        if not v.strip():
            raise ValueError("内容不能为空")
        return v.strip()

    @field_validator("pnl")
    @classmethod
    def pnl_valid(cls, v):
        if v is not None and (math.isnan(v) or math.isinf(v)):
            raise ValueError("盈亏必须为有限数字")
        return v

    @field_validator("mood")
    @classmethod
    def mood_valid(cls, v):
        if v is not None and (v < 1 or v > 5):
            raise ValueError("情绪评分必须在 1-5 之间")
        return v


@router.get("")
async def list_reviews(trade_date: str | None = None, limit: int = 20, offset: int = 0, q: str | None = None):
    """List reviews with pagination and search support."""
    db = await get_db()
    try:
        if trade_date:
            cursor = await db.execute(
                "SELECT * FROM reviews WHERE trade_date = ? ORDER BY created_at DESC",
                (trade_date,),
            )
        elif q:
            cursor = await db.execute(
                "SELECT * FROM reviews WHERE emotion_log LIKE ? OR ai_critique LIKE ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (f"%{q}%", f"%{q}%", limit, offset),
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM reviews ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


@router.get("/{review_id}")
async def get_review_detail(review_id: int):
    """Get full review detail with associated plans and weaknesses."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM reviews WHERE id = ?", (review_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="复盘不存在")
        review = dict(row)
        # Get plans for that day
        cursor = await db.execute(
            "SELECT content, plan_type FROM plans WHERE trade_date = ?", (review["trade_date"],)
        )
        review["plans"] = [dict(r) for r in await cursor.fetchall()]
        return review
    finally:
        await db.close()


@router.delete("/{review_id}")
async def delete_review(review_id: int):
    db = await get_db()
    try:
        cursor = await db.execute("DELETE FROM reviews WHERE id = ?", (review_id,))
        await db.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="复盘不存在")
        return {"ok": True}
    finally:
        await db.close()


@router.post("")
async def create_review(review: ReviewCreate):
    trade_date = review.trade_date or date.today().isoformat()

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT content FROM plans WHERE trade_date = ?", (trade_date,)
        )
        plan_rows = await cursor.fetchall()
        plans_text = "\n".join(f"- {row['content']}" for row in plan_rows) if plan_rows else "（今日无计划）"

        pnl_text = f"盈亏: {review.pnl}" if review.pnl is not None else "盈亏: 未填写"
        user_msg = f"""【今日计划】
{plans_text}

【实际结果】
{pnl_text}

【交易员倾诉】
{review.emotion_log}"""

        # Load intensity
        cursor = await db.execute("SELECT value FROM sys_config WHERE key = 'critique_intensity'")
        irow = await cursor.fetchone()
        intensity = irow["value"] if irow else "3"
        system_prompt = CRITIQUE_SYSTEM_PROMPT + INTENSITY_MODIFIERS.get(intensity, "")

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ]

        ai_critique = None
        try:
            ai_critique = await call_llm(messages)
        except Exception:
            ai_critique = None

        cursor = await db.execute(
            "INSERT INTO reviews (trade_date, pnl, emotion_log, ai_critique, mood) VALUES (?, ?, ?, ?, ?)",
            (trade_date, review.pnl, review.emotion_log, ai_critique, review.mood),
        )
        review_id = cursor.lastrowid
        await db.commit()

        if ai_critique:
            try:
                await _extract_weaknesses(db, review.emotion_log, ai_critique)
            except Exception:
                pass

        return {
            "id": review_id,
            "ai_critique": ai_critique,
            "ai_available": ai_critique is not None,
        }
    finally:
        await db.close()


@router.post("/stream")
async def create_review_stream(review: ReviewCreate):
    """Submit review with SSE streaming AI critique."""
    trade_date = review.trade_date or date.today().isoformat()

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT content FROM plans WHERE trade_date = ?", (trade_date,)
        )
        plan_rows = await cursor.fetchall()
        plans_text = "\n".join(f"- {row['content']}" for row in plan_rows) if plan_rows else "（今日无计划）"

        # Load active trade rules
        cursor = await db.execute("SELECT rule, category FROM trade_rules WHERE active = 1")
        rule_rows = await cursor.fetchall()
        rules_text = "\n".join(f"- [{row['category']}] {row['rule']}" for row in rule_rows) if rule_rows else ""
    finally:
        await db.close()

    pnl_text = f"盈亏: {review.pnl}" if review.pnl is not None else "盈亏: 未填写"
    mood_text = f"情绪评分: {review.mood}/5" if review.mood else "情绪评分: 未填写"
    user_msg = f"""【今日计划】
{plans_text}

{"【交易纪律规则】" + chr(10) + rules_text if rules_text else ""}

【实际结果】
{pnl_text}
{mood_text}

【交易员倾诉】
{review.emotion_log}"""

    # Load intensity setting
    db3 = await get_db()
    try:
        cursor = await db3.execute("SELECT value FROM sys_config WHERE key = 'critique_intensity'")
        row = await cursor.fetchone()
        intensity = row["value"] if row else "3"
    finally:
        await db3.close()

    system_prompt = CRITIQUE_SYSTEM_PROMPT + INTENSITY_MODIFIERS.get(intensity, "")
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]

    async def event_generator():
        full_critique = ""
        try:
            async for chunk in call_llm_stream(messages):
                full_critique += chunk
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            # Save without critique
            db2 = await get_db()
            try:
                await db2.execute(
                    "INSERT INTO reviews (trade_date, pnl, emotion_log, ai_critique, mood) VALUES (?, ?, ?, ?, ?)",
                    (trade_date, review.pnl, review.emotion_log, None, review.mood),
                )
                await db2.commit()
            finally:
                await db2.close()
            yield "data: [DONE]\n\n"
            return

        # Save review with full critique
        db2 = await get_db()
        try:
            cursor = await db2.execute(
                "INSERT INTO reviews (trade_date, pnl, emotion_log, ai_critique, mood) VALUES (?, ?, ?, ?, ?)",
                (trade_date, review.pnl, review.emotion_log, full_critique, review.mood),
            )
            review_id = cursor.lastrowid
            await db2.commit()
            # Extract weaknesses
            new_tags = []
            try:
                new_tags = await _extract_weaknesses(db2, review.emotion_log, full_critique)
            except Exception:
                pass
        finally:
            await db2.close()

        # Send feishu notification
        try:
            await send_review_notification(review.pnl, full_critique, new_tags)
        except Exception:
            pass

        # Check for big PnL alert
        if review.pnl is not None and review.pnl != 0:
            try:
                await send_big_pnl_alert(review.pnl)
            except Exception:
                pass

        yield f"data: {json.dumps({'done': True, 'review_id': review_id})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


async def _extract_weaknesses(db, emotion_log: str, critique: str) -> list[str]:
    """Extract weaknesses from review and update matrix. Returns list of new tags."""
    messages = [
        {"role": "system", "content": EXTRACT_WEAKNESS_PROMPT},
        {"role": "user", "content": f"交易员倾诉：{emotion_log}\n\n教练点评：{critique}"},
    ]
    raw = await call_llm(messages)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]

    weaknesses = json.loads(raw)
    if not isinstance(weaknesses, list):
        return []

    now = date.today().isoformat()
    tags = []
    for w in weaknesses:
        tag = w.get("tag", "").strip()
        severity = min(max(float(w.get("severity", 0.5)), 0.1), 1.0)
        if not tag:
            continue
        tags.append(tag)
        await db.execute("""
            INSERT INTO vulnerability_matrix (tag, weight, hit_count, last_hit_at, description)
            VALUES (?, ?, 1, ?, ?)
            ON CONFLICT(tag) DO UPDATE SET
                weight = weight + ? * 0.5,
                hit_count = hit_count + 1,
                last_hit_at = ?
        """, (tag, severity, now, tag, severity, now))
    await db.commit()
    return tags
