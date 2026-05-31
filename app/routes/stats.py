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
        month_ago = (today - timedelta(days=30)).isoformat()
        two_months_ago = (today - timedelta(days=60)).isoformat()

        # Total reviews & PnL
        cursor = await db.execute("SELECT COUNT(*) as cnt, COALESCE(SUM(pnl),0) as total FROM reviews")
        row = await cursor.fetchone()
        review_count = row["cnt"]
        total_pnl = row["total"]

        # This week reviews & PnL
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt, COALESCE(SUM(pnl),0) as total FROM reviews WHERE trade_date >= ?", (week_ago,)
        )
        wr = await cursor.fetchone()
        week_reviews = wr["cnt"]
        week_pnl = wr["total"]

        # This month PnL
        cursor = await db.execute(
            "SELECT COALESCE(SUM(pnl),0) as total FROM reviews WHERE trade_date >= ?", (month_ago,)
        )
        month_pnl = (await cursor.fetchone())["total"]

        # Last month PnL (30-60 days ago)
        cursor = await db.execute(
            "SELECT COALESCE(SUM(pnl),0) as total, COUNT(*) as cnt FROM reviews WHERE trade_date >= ? AND trade_date < ?",
            (two_months_ago, month_ago)
        )
        lm = await cursor.fetchone()
        last_month_pnl = lm["total"]
        last_month_trades = lm["cnt"]

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

        # Win rate
        cursor = await db.execute("SELECT COUNT(*) as cnt FROM reviews WHERE pnl > 0")
        wins = (await cursor.fetchone())["cnt"]
        cursor = await db.execute("SELECT COUNT(*) as cnt FROM reviews WHERE pnl IS NOT NULL AND pnl != 0")
        trades_with_pnl = (await cursor.fetchone())["cnt"]
        win_rate = (wins / trades_with_pnl * 100) if trades_with_pnl > 0 else 0

        # Max consecutive loss days
        cursor = await db.execute(
            "SELECT trade_date, SUM(pnl) as dp FROM reviews WHERE pnl IS NOT NULL GROUP BY trade_date ORDER BY trade_date"
        )
        all_days = await cursor.fetchall()
        max_loss_streak = 0
        cur_streak = 0
        for row in all_days:
            if row["dp"] < 0:
                cur_streak += 1
                max_loss_streak = max(max_loss_streak, cur_streak)
            else:
                cur_streak = 0

        # Profit factor & avg win/loss
        cursor = await db.execute("SELECT COALESCE(SUM(pnl),0) as s FROM reviews WHERE pnl > 0")
        gross_profit = (await cursor.fetchone())["s"]
        cursor = await db.execute("SELECT COALESCE(SUM(ABS(pnl)),0) as s FROM reviews WHERE pnl < 0")
        gross_loss = (await cursor.fetchone())["s"]
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 0
        cursor = await db.execute("SELECT COALESCE(AVG(pnl),0) as a FROM reviews WHERE pnl > 0")
        avg_win = (await cursor.fetchone())["a"]
        cursor = await db.execute("SELECT COALESCE(AVG(pnl),0) as a FROM reviews WHERE pnl < 0")
        avg_loss = (await cursor.fetchone())["a"]

        # Plan execution rate
        cursor = await db.execute("SELECT COUNT(*) as total, SUM(done) as completed FROM plans WHERE plan_type='today'")
        pr = await cursor.fetchone()
        plan_total = pr["total"]
        plan_done = pr["completed"] or 0
        plan_rate = (plan_done / plan_total * 100) if plan_total > 0 else 0

        # Mood trend (last 14 days)
        cursor = await db.execute(
            "SELECT trade_date, AVG(mood) as avg_mood FROM reviews WHERE trade_date >= ? AND mood IS NOT NULL GROUP BY trade_date ORDER BY trade_date",
            ((today - timedelta(days=13)).isoformat(),)
        )
        mood_trend = [{"trade_date": r["trade_date"], "avg_mood": round(r["avg_mood"], 1)} for r in await cursor.fetchall()]

        # Mood-PnL correlation
        cursor = await db.execute(
            "SELECT mood, AVG(pnl) as avg_pnl, COUNT(*) as cnt FROM reviews WHERE mood IS NOT NULL AND pnl IS NOT NULL GROUP BY mood ORDER BY mood"
        )
        mood_pnl_corr = [dict(r) for r in await cursor.fetchall()]

        # Weekday performance
        cursor = await db.execute(
            "SELECT CAST(strftime('%w', trade_date) AS INTEGER) as dow, AVG(pnl) as avg_pnl, COUNT(*) as cnt "
            "FROM reviews WHERE pnl IS NOT NULL GROUP BY dow ORDER BY dow"
        )
        weekday_perf = [dict(r) for r in await cursor.fetchall()]

        # Top weaknesses
        cursor = await db.execute(
            "SELECT tag, weight, hit_count FROM vulnerability_matrix ORDER BY hit_count DESC LIMIT 5"
        )
        top_weaknesses = [dict(r) for r in await cursor.fetchall()]

        # Daily PnL for last 14 days (for trend chart)
        cursor = await db.execute(
            "SELECT trade_date, SUM(pnl) as daily_pnl FROM reviews WHERE trade_date >= ? GROUP BY trade_date ORDER BY trade_date",
            ((today - timedelta(days=13)).isoformat(),)
        )
        pnl_trend = [dict(r) for r in await cursor.fetchall()]

        # Drawdown analysis (cumulative equity curve)
        cursor = await db.execute(
            "SELECT trade_date, SUM(pnl) as daily_pnl FROM reviews WHERE pnl IS NOT NULL GROUP BY trade_date ORDER BY trade_date"
        )
        all_daily = await cursor.fetchall()
        cumulative = 0
        peak = 0
        max_dd = 0
        current_dd = 0
        for row in all_daily:
            cumulative += row["daily_pnl"] or 0
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_dd:
                max_dd = dd
        current_dd = peak - cumulative if peak > cumulative else 0

        return {
            "review_count": review_count,
            "total_pnl": float(total_pnl),
            "week_reviews": week_reviews,
            "week_pnl": float(week_pnl),
            "month_pnl": float(month_pnl),
            "streak_days": streak,
            "win_rate": round(win_rate, 1),
            "max_loss_streak": max_loss_streak,
            "profit_factor": round(profit_factor, 2),
            "avg_win": round(float(avg_win), 1),
            "avg_loss": round(float(avg_loss), 1),
            "plan_rate": round(plan_rate, 1),
            "top_weaknesses": top_weaknesses,
            "pnl_trend": pnl_trend,
            "mood_trend": mood_trend,
            "mood_pnl_corr": mood_pnl_corr,
            "max_drawdown": round(max_dd, 1),
            "current_drawdown": round(current_dd, 1),
            "last_month_pnl": float(last_month_pnl),
            "last_month_trades": last_month_trades,
            "weekday_perf": weekday_perf,
        }
    finally:
        await db.close()
