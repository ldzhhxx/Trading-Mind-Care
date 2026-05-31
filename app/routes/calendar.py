"""Calendar routes - monthly PnL overview."""
from fastapi import APIRouter
from datetime import date
from app.database import get_db

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


@router.get("")
async def get_calendar(year: int | None = None, month: int | None = None):
    """Return daily PnL data for a given month."""
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
            "SELECT trade_date, SUM(pnl) as daily_pnl, COUNT(*) as cnt "
            "FROM reviews WHERE trade_date >= ? AND trade_date < ? GROUP BY trade_date",
            (start, end),
        )
        days = {}
        for row in await cursor.fetchall():
            days[row["trade_date"]] = {"pnl": row["daily_pnl"], "count": row["cnt"]}

        # Plan execution per day
        cursor = await db.execute(
            "SELECT trade_date, COUNT(*) as total, SUM(done) as done "
            "FROM plans WHERE trade_date >= ? AND trade_date < ? AND plan_type='today' GROUP BY trade_date",
            (start, end),
        )
        for row in await cursor.fetchall():
            d = row["trade_date"]
            if d not in days:
                days[d] = {"pnl": None, "count": 0}
            days[d]["plan_total"] = row["total"]
            days[d]["plan_done"] = row["done"] or 0

        total_pnl = sum(d.get("pnl") or 0 for d in days.values())
        trade_days = sum(1 for d in days.values() if d.get("count", 0) > 0)
        return {"year": y, "month": m, "days": days, "month_pnl": total_pnl, "trade_days": trade_days}
    finally:
        await db.close()
