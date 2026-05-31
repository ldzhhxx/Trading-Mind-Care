"""Monthly report route - comprehensive monthly analysis."""
import json
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from datetime import date, timedelta
from app.database import get_db
from app.llm import call_llm_stream

router = APIRouter(prefix="/api/monthly", tags=["monthly"])

MONTHLY_SYSTEM_PROMPT = """你是一个交易心理教练，正在为交易员做月度总结。基于数据，给出：
1. 本月整体表现评价（一句话）
2. 最突出的进步
3. 最需要改善的问题
4. 下月核心目标（1-2个）
5. 一个具体的行动建议

简洁有力，不超过 250 字。"""


@router.get("/data")
async def get_monthly_data(year: int | None = None, month: int | None = None):
    """Return monthly summary data."""
    today = date.today()
    y = year or today.year
    m = month or today.month
    start = f"{y:04d}-{m:02d}-01"
    if m == 12:
        end = f"{y + 1:04d}-01-01"
    else:
        end = f"{y:04d}-{m + 1:02d}-01"

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt, COALESCE(SUM(pnl),0) as total, "
            "COALESCE(AVG(pnl),0) as avg_pnl FROM reviews WHERE trade_date >= ? AND trade_date < ?",
            (start, end)
        )
        r = await cursor.fetchone()

        cursor = await db.execute(
            "SELECT COUNT(*) as wins FROM reviews WHERE trade_date >= ? AND trade_date < ? AND pnl > 0",
            (start, end)
        )
        wins = (await cursor.fetchone())["wins"]

        cursor = await db.execute(
            "SELECT COUNT(*) as total, SUM(done) as done FROM plans WHERE trade_date >= ? AND trade_date < ? AND plan_type='today'",
            (start, end)
        )
        pr = await cursor.fetchone()
        plan_rate = ((pr["done"] or 0) / pr["total"] * 100) if pr["total"] else 0

        cursor = await db.execute(
            "SELECT tag, weight, hit_count FROM vulnerability_matrix ORDER BY hit_count DESC LIMIT 5"
        )
        top_vulns = [dict(v) for v in await cursor.fetchall()]

        return {
            "year": y, "month": m,
            "trade_days": r["cnt"],
            "total_pnl": float(r["total"]),
            "avg_pnl": round(float(r["avg_pnl"]), 1),
            "win_rate": round(wins / r["cnt"] * 100, 1) if r["cnt"] else 0,
            "plan_rate": round(plan_rate, 1),
            "top_vulns": top_vulns,
        }
    finally:
        await db.close()


@router.post("/generate")
async def generate_monthly_summary(year: int | None = None, month: int | None = None):
    """Generate AI monthly summary via SSE stream."""
    today = date.today()
    y = year or today.year
    m = month or today.month
    start = f"{y:04d}-{m:02d}-01"
    if m == 12:
        end = f"{y + 1:04d}-01-01"
    else:
        end = f"{y:04d}-{m + 1:02d}-01"

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT trade_date, pnl, emotion_log FROM reviews WHERE trade_date >= ? AND trade_date < ? ORDER BY trade_date",
            (start, end)
        )
        reviews = [dict(r) for r in await cursor.fetchall()]
        cursor = await db.execute(
            "SELECT tag, weight, hit_count FROM vulnerability_matrix ORDER BY weight DESC LIMIT 5"
        )
        vulns = [dict(r) for r in await cursor.fetchall()]
        cursor = await db.execute(
            "SELECT COUNT(*) as total, SUM(done) as done FROM plans WHERE trade_date >= ? AND trade_date < ? AND plan_type='today'",
            (start, end)
        )
        pr = await cursor.fetchone()
    finally:
        await db.close()

    total_pnl = sum(r["pnl"] or 0 for r in reviews)
    wins = sum(1 for r in reviews if r["pnl"] and r["pnl"] > 0)
    plan_rate = ((pr["done"] or 0) / pr["total"] * 100) if pr["total"] else 0
    vulns_text = ", ".join(f"{v['tag']}({v['weight']:.1f})" for v in vulns) if vulns else "无"

    win_rate = f"{wins/len(reviews)*100:.0f}%" if reviews else "0%"
    user_msg = f"""【{y}年{m}月数据】
交易天数: {len(reviews)}
总盈亏: {total_pnl:.1f}
胜率: {wins}/{len(reviews)} ({win_rate})
计划执行率: {plan_rate:.0f}%
活跃弱点: {vulns_text}"""

    messages = [
        {"role": "system", "content": MONTHLY_SYSTEM_PROMPT},
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
