"""Weekly summary routes - AI-generated weekly analysis."""
import json
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from datetime import date, timedelta
from app.database import get_db
from app.llm import call_llm_stream

router = APIRouter(prefix="/api/weekly", tags=["weekly"])

WEEKLY_SYSTEM_PROMPT = """你是一个交易心理教练，正在为交易员做每周总结。你需要：
1. 总结本周交易表现（盈亏、交易天数）
2. 分析本周暴露的主要心理弱点和行为模式
3. 指出进步的地方（如果有）
4. 给出下周需要重点注意的 2-3 条建议
保持尖锐但有建设性，300字以内。"""


@router.get("/data")
async def get_weekly_data():
    """Return raw weekly data for display."""
    today = date.today()
    week_start = (today - timedelta(days=today.weekday())).isoformat()
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT trade_date, pnl, emotion_log, ai_critique FROM reviews WHERE trade_date >= ? ORDER BY trade_date",
            (week_start,),
        )
        reviews = [dict(r) for r in await cursor.fetchall()]
        cursor = await db.execute(
            "SELECT tag, weight, hit_count FROM vulnerability_matrix ORDER BY weight DESC LIMIT 5"
        )
        top_vulns = [dict(r) for r in await cursor.fetchall()]
        total_pnl = sum(r["pnl"] or 0 for r in reviews)
        return {"week_start": week_start, "review_count": len(reviews), "total_pnl": total_pnl, "top_vulns": top_vulns}
    finally:
        await db.close()


@router.post("/generate")
async def generate_weekly_summary():
    """Generate AI weekly summary via SSE stream."""
    today = date.today()
    week_start = (today - timedelta(days=today.weekday())).isoformat()

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT trade_date, pnl, emotion_log, ai_critique FROM reviews WHERE trade_date >= ? ORDER BY trade_date",
            (week_start,),
        )
        reviews = [dict(r) for r in await cursor.fetchall()]
        cursor = await db.execute(
            "SELECT tag, weight, hit_count FROM vulnerability_matrix ORDER BY weight DESC LIMIT 5"
        )
        vulns = [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()

    # Build context
    review_lines = []
    for r in reviews:
        pnl_str = f"盈亏{r['pnl']}" if r["pnl"] is not None else "未记录盈亏"
        review_lines.append(f"- {r['trade_date']}: {pnl_str}，倾诉：{r['emotion_log'][:100]}")
    reviews_text = "\n".join(review_lines) if review_lines else "本周无复盘记录"
    vulns_text = ", ".join(f"{v['tag']}(权重{v['weight']:.1f})" for v in vulns) if vulns else "无"
    total_pnl = sum(r["pnl"] or 0 for r in reviews)

    user_msg = f"""【本周数据 {week_start} ~ {today.isoformat()}】
交易天数: {len(reviews)}
总盈亏: {total_pnl}
当前弱点矩阵 TOP5: {vulns_text}

【每日复盘摘要】
{reviews_text}"""

    messages = [
        {"role": "system", "content": WEEKLY_SYSTEM_PROMPT},
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
