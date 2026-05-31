"""Discipline violation tracking and trader level system (v9.0)."""
import json
from fastapi import APIRouter
from datetime import date, timedelta
from app.database import get_db

router = APIRouter(prefix="/api/discipline", tags=["discipline"])


@router.get("/violations")
async def list_violations(limit: int = 50):
    """List discipline violation history."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM discipline_violations ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


@router.post("/violations")
async def record_violation(content: dict):
    """Record a discipline violation."""
    rule_text = content.get("rule_text", "")
    category = content.get("category", "general")
    evidence = content.get("evidence", "")
    review_id = content.get("review_id")
    trade_date = content.get("trade_date") or date.today().isoformat()
    rule_id = content.get("rule_id")

    if not rule_text.strip():
        return {"error": "规则内容不能为空"}

    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO discipline_violations (trade_date, rule_id, rule_text, category, evidence, review_id) VALUES (?, ?, ?, ?, ?, ?)",
            (trade_date, rule_id, rule_text, category, evidence, review_id),
        )
        await db.commit()
        # Deduct XP for violation
        await _add_xp(db, "violation", -10, trade_date)
        return {"ok": True}
    finally:
        await db.close()


@router.get("/violations/stats")
async def violation_stats():
    """Violation statistics and improvement trends."""
    db = await get_db()
    try:
        # Total violations
        cursor = await db.execute("SELECT COUNT(*) as total FROM discipline_violations")
        total = (await cursor.fetchone())["total"]

        # By category
        cursor = await db.execute(
            "SELECT category, COUNT(*) as cnt FROM discipline_violations GROUP BY category ORDER BY cnt DESC"
        )
        by_category = [dict(r) for r in await cursor.fetchall()]

        # Weekly trend (last 8 weeks)
        weeks = []
        today = date.today()
        for i in range(8):
            week_end = today - timedelta(days=today.weekday() + i * 7)
            week_start = week_end - timedelta(days=6)
            cursor = await db.execute(
                "SELECT COUNT(*) as cnt FROM discipline_violations WHERE trade_date >= ? AND trade_date <= ?",
                (week_start.isoformat(), week_end.isoformat()),
            )
            weeks.append({"week": week_start.isoformat(), "count": (await cursor.fetchone())["cnt"]})
        weeks.reverse()

        # Most violated rules
        cursor = await db.execute(
            "SELECT rule_text, COUNT(*) as cnt FROM discipline_violations GROUP BY rule_text ORDER BY cnt DESC LIMIT 5"
        )
        top_rules = [dict(r) for r in await cursor.fetchall()]

        return {"total": total, "by_category": by_category, "weekly_trend": weeks, "top_violated_rules": top_rules}
    finally:
        await db.close()


@router.get("/level")
async def get_trader_level():
    """Get trader level, XP, and progress."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT SUM(xp) as total_xp FROM trader_xp")
        row = await cursor.fetchone()
        total_xp = max(0, row["total_xp"] or 0)

        # Level thresholds
        levels = [
            (0, "新手交易员", "🌱"),
            (100, "纪律学徒", "📘"),
            (300, "自律战士", "⚔️"),
            (600, "心态修行者", "🧘"),
            (1000, "纪律大师", "🏅"),
            (1500, "交易哲人", "🎓"),
            (2500, "市场智者", "👑"),
        ]

        current_level = levels[0]
        next_level = levels[1] if len(levels) > 1 else None
        for i, (threshold, name, icon) in enumerate(levels):
            if total_xp >= threshold:
                current_level = (threshold, name, icon)
                next_level = levels[i + 1] if i + 1 < len(levels) else None

        # Recent XP history
        cursor = await db.execute(
            "SELECT action, xp, trade_date FROM trader_xp ORDER BY created_at DESC LIMIT 10"
        )
        history = [dict(r) for r in await cursor.fetchall()]

        # Today's XP
        cursor = await db.execute(
            "SELECT SUM(xp) as today_xp FROM trader_xp WHERE trade_date = ?",
            (date.today().isoformat(),)
        )
        today_xp = (await cursor.fetchone())["today_xp"] or 0

        progress = 0
        if next_level:
            range_xp = next_level[0] - current_level[0]
            progress = round((total_xp - current_level[0]) / range_xp * 100) if range_xp > 0 else 100

        return {
            "total_xp": total_xp,
            "level_name": current_level[1],
            "level_icon": current_level[2],
            "next_level": next_level[1] if next_level else None,
            "next_threshold": next_level[0] if next_level else None,
            "progress": min(100, progress),
            "today_xp": today_xp,
            "history": history,
        }
    finally:
        await db.close()


@router.post("/xp")
async def add_xp_endpoint(content: dict):
    """Manually add XP (used by other systems)."""
    action = content.get("action", "")
    xp = content.get("xp", 0)
    trade_date = content.get("trade_date") or date.today().isoformat()

    if not action:
        return {"error": "action required"}

    db = await get_db()
    try:
        await _add_xp(db, action, xp, trade_date)
        return {"ok": True}
    finally:
        await db.close()


async def _add_xp(db, action: str, xp: int, trade_date: str):
    """Internal: add XP record."""
    await db.execute(
        "INSERT INTO trader_xp (action, xp, trade_date) VALUES (?, ?, ?)",
        (action, xp, trade_date),
    )
    await db.commit()
