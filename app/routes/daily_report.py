"""Daily report route - combines plans, reviews, and weaknesses for a date."""
from fastapi import APIRouter
from datetime import date, timedelta
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


@router.get("/dashboard")
async def get_dashboard():
    """首页仪表盘 — 一眼看清今日状态."""
    today = date.today()
    db = await get_db()
    try:
        # Today's plans
        cursor = await db.execute(
            "SELECT COUNT(*) as total, SUM(done) as done FROM plans WHERE trade_date = ? AND plan_type='today'",
            (today.isoformat(),)
        )
        plan_row = await cursor.fetchone()
        plan_total = plan_row["total"]
        plan_done = plan_row["done"] or 0

        # Today's PnL
        cursor = await db.execute(
            "SELECT SUM(pnl) as pnl, COUNT(*) as cnt FROM reviews WHERE trade_date = ? AND pnl IS NOT NULL",
            (today.isoformat(),)
        )
        review_row = await cursor.fetchone()
        today_pnl = review_row["pnl"] or 0
        today_reviews = review_row["cnt"]

        # Streak
        streak = 0
        d = today
        while True:
            cursor = await db.execute("SELECT COUNT(*) as cnt FROM reviews WHERE trade_date = ?", (d.isoformat(),))
            if (await cursor.fetchone())["cnt"] > 0:
                streak += 1
                d -= timedelta(days=1)
            else:
                break

        # Top weakness
        cursor = await db.execute(
            "SELECT tag, weight FROM vulnerability_matrix ORDER BY weight DESC LIMIT 1"
        )
        top_vuln = await cursor.fetchone()

        # Week PnL
        week_start = (today - timedelta(days=today.weekday())).isoformat()
        cursor = await db.execute(
            "SELECT SUM(pnl) as pnl FROM reviews WHERE trade_date >= ? AND pnl IS NOT NULL",
            (week_start,)
        )
        week_pnl = (await cursor.fetchone())["pnl"] or 0

        # Trader level
        cursor = await db.execute("SELECT SUM(xp) as total_xp FROM trader_xp")
        xp_row = await cursor.fetchone()
        total_xp = max(0, (xp_row["total_xp"] or 0))

        # Today's violations
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM discipline_violations WHERE trade_date = ?",
            (today.isoformat(),)
        )
        today_violations = (await cursor.fetchone())["cnt"]

        return {
            "date": today.isoformat(),
            "plan_total": plan_total,
            "plan_done": plan_done,
            "plan_rate": round(plan_done / plan_total * 100) if plan_total else 0,
            "today_pnl": round(today_pnl, 1),
            "today_reviews": today_reviews,
            "streak": streak,
            "week_pnl": round(week_pnl, 1),
            "top_weakness": top_vuln["tag"] if top_vuln else None,
            "top_weakness_weight": round(top_vuln["weight"], 1) if top_vuln else 0,
            "total_xp": total_xp,
            "today_violations": today_violations,
        }
    finally:
        await db.close()
