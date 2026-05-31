"""Goals & habits tracking routes."""
from fastapi import APIRouter
from pydantic import BaseModel, field_validator
from datetime import date, timedelta
from app.database import get_db

router = APIRouter(prefix="/api/goals", tags=["goals"])


class GoalCreate(BaseModel):
    title: str
    goal_type: str = "monthly"  # monthly / weekly
    target_month: str  # YYYY-MM

    @field_validator("title")
    @classmethod
    def title_valid(cls, v):
        v = v.strip()
        if not v or len(v) > 200:
            raise ValueError("标题1-200字")
        return v


@router.get("")
async def list_goals(month: str | None = None):
    """List goals, optionally filtered by month."""
    db = await get_db()
    try:
        if month:
            cursor = await db.execute(
                "SELECT * FROM goals WHERE target_month = ? ORDER BY created_at DESC", (month,)
            )
        else:
            cursor = await db.execute("SELECT * FROM goals ORDER BY created_at DESC LIMIT 20")
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


@router.post("")
async def create_goal(goal: GoalCreate):
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO goals (title, goal_type, target_month) VALUES (?, ?, ?)",
            (goal.title, goal.goal_type, goal.target_month),
        )
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


@router.post("/{goal_id}/complete")
async def complete_goal(goal_id: int):
    db = await get_db()
    try:
        await db.execute(
            "UPDATE goals SET status = 'completed', completed_at = datetime('now','localtime') WHERE id = ?",
            (goal_id,),
        )
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


@router.post("/{goal_id}/fail")
async def fail_goal(goal_id: int):
    db = await get_db()
    try:
        await db.execute("UPDATE goals SET status = 'failed' WHERE id = ?", (goal_id,))
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


@router.delete("/{goal_id}")
async def delete_goal(goal_id: int):
    db = await get_db()
    try:
        await db.execute("DELETE FROM goals WHERE id = ?", (goal_id,))
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


@router.get("/streaks")
async def get_streaks():
    """Get habit streaks: consecutive review days, plan days, etc."""
    db = await get_db()
    try:
        today = date.today()

        # Review streak
        review_streak = 0
        d = today
        while True:
            cursor = await db.execute(
                "SELECT COUNT(*) as cnt FROM reviews WHERE trade_date = ?", (d.isoformat(),)
            )
            if (await cursor.fetchone())["cnt"] > 0:
                review_streak += 1
                d -= timedelta(days=1)
            else:
                break

        # Plan streak (days with at least one plan created)
        plan_streak = 0
        d = today
        while True:
            cursor = await db.execute(
                "SELECT COUNT(*) as cnt FROM plans WHERE trade_date = ?", (d.isoformat(),)
            )
            if (await cursor.fetchone())["cnt"] > 0:
                plan_streak += 1
                d -= timedelta(days=1)
            else:
                break

        # Best review streak ever
        cursor = await db.execute(
            "SELECT DISTINCT trade_date FROM reviews ORDER BY trade_date DESC"
        )
        all_dates = [r["trade_date"] for r in await cursor.fetchall()]
        best_streak = 0
        cur = 0
        prev = None
        for ds in all_dates:
            d2 = date.fromisoformat(ds)
            if prev is None or (prev - d2).days == 1:
                cur += 1
            else:
                cur = 1
            best_streak = max(best_streak, cur)
            prev = d2

        # Total review days
        cursor = await db.execute("SELECT COUNT(DISTINCT trade_date) as cnt FROM reviews")
        total_review_days = (await cursor.fetchone())["cnt"]

        # This month goal progress
        this_month = today.strftime("%Y-%m")
        cursor = await db.execute(
            "SELECT COUNT(*) as total, SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) as done "
            "FROM goals WHERE target_month = ?", (this_month,)
        )
        gr = await cursor.fetchone()

        return {
            "review_streak": review_streak,
            "plan_streak": plan_streak,
            "best_streak": best_streak,
            "total_review_days": total_review_days,
            "month_goals_total": gr["total"],
            "month_goals_done": gr["done"] or 0,
        }
    finally:
        await db.close()
