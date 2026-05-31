"""APScheduler setup for daily tasks."""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import date
from app.database import get_db
from app.feishu import send_daily_notification, send_plan_incomplete_alert

scheduler = AsyncIOScheduler()


async def daily_decay():
    """Decay all vulnerability weights once per day."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT value FROM sys_config WHERE key = 'last_decay_date'")
        row = await cursor.fetchone()
        today = date.today().isoformat()
        if row and row["value"] == today:
            return

        # Get configurable decay rate
        cursor = await db.execute("SELECT value FROM sys_config WHERE key = 'decay_rate'")
        dr = await cursor.fetchone()
        decay_rate = float(dr["value"]) if dr and dr["value"] else 0.98

        await db.execute(f"UPDATE vulnerability_matrix SET weight = weight * ? WHERE weight > 0.1", (decay_rate,))
        await db.execute(
            "INSERT OR REPLACE INTO sys_config (key, value) VALUES ('last_decay_date', ?)",
            (today,),
        )
        await db.commit()
    finally:
        await db.close()


def start_scheduler():
    # Daily notification at configured time (default 8:30)
    scheduler.add_job(send_daily_notification, CronTrigger(hour=8, minute=30), id="daily_notify", replace_existing=True)
    # Daily decay at midnight
    scheduler.add_job(daily_decay, CronTrigger(hour=0, minute=5), id="daily_decay", replace_existing=True)
    # Plan incomplete reminder at 20:00
    scheduler.add_job(send_plan_incomplete_alert, CronTrigger(hour=20, minute=0), id="plan_incomplete", replace_existing=True)
    scheduler.start()
