"""AI Coach - free-form trading conversation mode (v7.0)."""
import json
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
from app.database import get_db
from app.llm import call_llm_stream

router = APIRouter(prefix="/api/coach", tags=["coach"])

COACH_SYSTEM = """你是一个专业的交易心理教练，拥有丰富的交易心理学和行为金融学知识。

你的角色：
- 随时可以和交易员讨论任何交易相关问题（心态、策略、纪律、情绪管理等）
- 基于用户的历史数据（弱点、盈亏、情绪模式）给出个性化建议
- 用苏格拉底式提问引导交易员自我反思
- 直击要害，不说废话，每句话都有信息量
- 如果交易员在逃避问题，你要温和但坚定地把他拉回来

你不是：
- 不是交易信号提供者（不推荐买卖）
- 不是心灵鸡汤（不说空洞的鼓励）
- 不是情绪垃圾桶（引导解决问题而非单纯倾听）

回复控制在 200 字以内，除非用户明确要求详细分析。"""


class ChatMessage(BaseModel):
    message: str
    history: list[dict] = []

    @field_validator("message")
    @classmethod
    def msg_valid(cls, v):
        if not v.strip():
            raise ValueError("消息不能为空")
        if len(v) > 2000:
            raise ValueError("消息不能超过 2000 字符")
        return v.strip()


@router.post("/chat")
async def coach_chat(req: ChatMessage):
    """AI 教练对话 — 随时讨论交易问题."""
    # Gather user context
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT tag, weight FROM vulnerability_matrix WHERE weight >= 1.0 ORDER BY weight DESC LIMIT 5"
        )
        vulns = [dict(r) for r in await cursor.fetchall()]
        cursor = await db.execute(
            "SELECT pnl, mood, trade_date FROM reviews WHERE pnl IS NOT NULL ORDER BY trade_date DESC LIMIT 5"
        )
        recent = [dict(r) for r in await cursor.fetchall()]
        # Get active rules for context
        cursor = await db.execute("SELECT rule, category FROM trade_rules WHERE active = 1 LIMIT 5")
        rules = [dict(r) for r in await cursor.fetchall()]
        # Get goals
        from datetime import date
        this_month = date.today().strftime("%Y-%m")
        cursor = await db.execute(
            "SELECT title, status FROM goals WHERE target_month = ? LIMIT 3", (this_month,)
        )
        goals = [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()

    context_parts = []
    if vulns:
        context_parts.append("用户当前弱点：" + ", ".join(f"{v['tag']}({v['weight']:.1f})" for v in vulns))
    if recent:
        pnl_str = ", ".join(f"{r['trade_date']}:{r['pnl']:+.0f}" for r in recent)
        context_parts.append(f"近期盈亏：{pnl_str}")
    if rules:
        context_parts.append("交易纪律：" + "; ".join(f"[{r['category']}]{r['rule']}" for r in rules))
    if goals:
        context_parts.append("本月目标：" + ", ".join(f"{g['title']}({g['status']})" for g in goals))

    system = COACH_SYSTEM
    if context_parts:
        system += "\n\n【用户画像】\n" + "\n".join(context_parts)

    messages = [{"role": "system", "content": system}]
    # Add conversation history (last 10 turns)
    for h in req.history[-10:]:
        if h.get("role") in ("user", "assistant"):
            messages.append({"role": h["role"], "content": h["content"][:500]})
    messages.append({"role": "user", "content": req.message})

    async def stream():
        try:
            async for chunk in call_llm_stream(messages):
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
