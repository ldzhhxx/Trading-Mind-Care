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
        days = {row["trade_date"]: {"pnl": row["daily_pnl"], "count": row["cnt"]} for row in await cursor.fetchall()}
        return {"year": y, "month": m, "days": days}
    finally:
        await db.close()
