"""AI insights route - personalized daily advice based on patterns."""
import json
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from datetime import date, timedelta
from app.database import get_db
from app.llm import call_llm_stream

router = APIRouter(prefix="/api/insights", tags=["insights"])

INSIGHT_SYSTEM_PROMPT = """你是一个交易心理教练，正在为交易员生成今日个性化建议。基于他最近的数据模式，给出：
1. 一句话总结当前状态（好/差/需注意）
2. 今日最需要警惕的 1-2 个具体行为
3. 一条可执行的建议

要求：简洁有力，不超过 150 字。不要空洞的鼓励。"""


@router.post("/daily")
async def generate_daily_insight():
    """Generate personalized daily insight via SSE stream."""
    today = date.today()
    week_ago = (today - timedelta(days=7)).isoformat()

    db = await get_db()
    try:
        # Recent PnL
        cursor = await db.execute(
            "SELECT trade_date, pnl, mood FROM reviews WHERE trade_date >= ? ORDER BY trade_date DESC", (week_ago,)
        )
        recent = [dict(r) for r in await cursor.fetchall()]

        # Top active weaknesses
        cursor = await db.execute(
            "SELECT tag, weight, hit_count FROM vulnerability_matrix WHERE weight >= 1.0 ORDER BY weight DESC LIMIT 5"
        )
        vulns = [dict(r) for r in await cursor.fetchall()]

        # Plan execution rate this week
        cursor = await db.execute(
            "SELECT COUNT(*) as total, SUM(done) as done FROM plans WHERE trade_date >= ? AND plan_type='today'", (week_ago,)
        )
        pr = await cursor.fetchone()
        plan_rate = (pr["done"] or 0) / pr["total"] * 100 if pr["total"] else 0

        # Consecutive loss check
        streak = 0
        for r in recent:
            if r["pnl"] is not None and r["pnl"] < 0:
                streak += 1
            else:
                break
    finally:
        await db.close()

    # Build context
    pnl_summary = ", ".join(f"{r['trade_date'][-5:]}: {r['pnl']}" for r in recent[:5]) if recent else "无近期数据"
    mood_summary = ", ".join(f"{r['mood']}/5" for r in recent[:5] if r.get("mood")) or "未记录"
    vulns_text = ", ".join(f"{v['tag']}({v['weight']:.1f})" for v in vulns) if vulns else "无"

    user_msg = f"""【近7日盈亏】{pnl_summary}
【近期情绪】{mood_summary}
【连亏天数】{streak}
【计划执行率】{plan_rate:.0f}%
【活跃弱点】{vulns_text}"""

    messages = [
        {"role": "system", "content": INSIGHT_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    async def stream():
        try:
            async for chunk in call_llm_stream(messages):
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
