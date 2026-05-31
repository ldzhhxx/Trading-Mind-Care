"""Statistics routes."""
from fastapi import APIRouter
from datetime import date, timedelta
from app.database import get_db

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("")
async def get_stats():
    """Return aggregated statistics."""
    db = await get_db()
    try:
        today = date.today()
        week_ago = (today - timedelta(days=7)).isoformat()

        # Total reviews & PnL
        cursor = await db.execute("SELECT COUNT(*) as cnt, COALESCE(SUM(pnl),0) as total FROM reviews")
        row = await cursor.fetchone()
        review_count = row["cnt"]
        total_pnl = row["total"]

        # This week reviews
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM reviews WHERE trade_date >= ?", (week_ago,)
        )
        week_reviews = (await cursor.fetchone())["cnt"]

        # Streak: consecutive days with reviews ending today
        streak = 0
        d = today
        while True:
            cursor = await db.execute(
                "SELECT COUNT(*) as cnt FROM reviews WHERE trade_date = ?", (d.isoformat(),)
            )
            if (await cursor.fetchone())["cnt"] > 0:
                streak += 1
                d -= timedelta(days=1)
            else:
                break

        # Top weaknesses
        cursor = await db.execute(
            "SELECT tag, weight, hit_count FROM vulnerability_matrix ORDER BY weight DESC LIMIT 5"
        )
        top_weaknesses = [dict(r) for r in await cursor.fetchall()]

        return {
            "review_count": review_count,
            "total_pnl": float(total_pnl),
            "week_reviews": week_reviews,
            "streak_days": streak,
            "top_weaknesses": top_weaknesses,
        }
    finally:
        await db.close()
