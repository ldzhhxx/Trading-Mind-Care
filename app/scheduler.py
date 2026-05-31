"""APScheduler setup for daily tasks."""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import date
from app.database import get_db
from app.feishu import send_daily_notification

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

        await db.execute("UPDATE vulnerability_matrix SET weight = weight * 0.98 WHERE weight > 0.1")
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
    scheduler.start()
