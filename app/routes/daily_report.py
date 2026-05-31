"""Daily report route - combines plans, reviews, and weaknesses for a date."""
from fastapi import APIRouter
from datetime import date
from app.database import get_db

router = APIRouter(prefix="/api/daily-report", tags=["daily-report"])


@router.get("")
async def get_daily_report(trade_date: str | None = None):
    trade_date = trade_date or date.today().isoformat()
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM plans WHERE trade_date = ? ORDER BY created_at", (trade_date,)
        )
        plans = [dict(r) for r in await cursor.fetchall()]

        cursor = await db.execute(
            "SELECT * FROM reviews WHERE trade_date = ? ORDER BY created_at", (trade_date,)
        )
        reviews = [dict(r) for r in await cursor.fetchall()]

        total_pnl = sum(r["pnl"] or 0 for r in reviews)

        return {
            "trade_date": trade_date,
            "plans": plans,
            "reviews": reviews,
            "total_pnl": total_pnl,
        }
    finally:
        await db.close()
