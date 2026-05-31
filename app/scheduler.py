"""APScheduler setup for daily tasks."""
import logging
import os
import shutil
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import date, datetime
from app.database import get_db, get_db_path
from app.feishu import send_daily_notification, send_plan_incomplete_alert, send_no_review_alert, send_risk_alert

logger = logging.getLogger(__name__)
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

        cursor = await db.execute("SELECT value FROM sys_config WHERE key = 'decay_rate'")
        dr = await cursor.fetchone()
        decay_rate = float(dr["value"]) if dr and dr["value"] else 0.98

        # Clamp decay rate to valid range
        decay_rate = max(0.8, min(1.0, decay_rate))

        await db.execute("UPDATE vulnerability_matrix SET weight = weight * ? WHERE weight > 0.1", (decay_rate,))
        await db.execute(
            "INSERT OR REPLACE INTO sys_config (key, value) VALUES ('last_decay_date', ?)",
            (today,),
        )

        # Record weight history for decay visualization
        cursor = await db.execute("SELECT tag, weight FROM vulnerability_matrix WHERE weight > 0.1")
        vulns = await cursor.fetchall()
        for v in vulns:
            await db.execute(
                "INSERT INTO vuln_weight_history (tag, weight, recorded_at) VALUES (?, ?, ?)",
                (v["tag"], v["weight"], today),
            )

        await db.commit()
        logger.info(f"Daily decay applied (rate={decay_rate})")
    except Exception as e:
        logger.error(f"Daily decay failed: {e}")
    finally:
        await db.close()


async def daily_auto_backup():
    """Create daily automatic backup, keep last 7."""
    try:
        db_path = get_db_path()
        backup_dir = os.path.join(os.path.dirname(db_path), "backups")
        os.makedirs(backup_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(backup_dir, f"mind_care_{timestamp}.db")
        shutil.copy2(db_path, backup_path)

        # Keep only last 7
        existing = sorted([f for f in os.listdir(backup_dir) if f.endswith(".db")], reverse=True)
        for old in existing[7:]:
            try:
                os.remove(os.path.join(backup_dir, old))
            except Exception:
                pass
        logger.info(f"Daily backup created: {backup_path}")
    except Exception as e:
        logger.error(f"Daily backup failed: {e}")


def start_scheduler():
    """Start background scheduler for daily tasks."""
    scheduler.add_job(send_daily_notification, CronTrigger(hour=8, minute=30), id="daily_notify", replace_existing=True)
    scheduler.add_job(daily_decay, CronTrigger(hour=0, minute=5), id="daily_decay", replace_existing=True)
    scheduler.add_job(send_plan_incomplete_alert, CronTrigger(hour=20, minute=0), id="plan_incomplete", replace_existing=True)
    scheduler.add_job(daily_auto_backup, CronTrigger(hour=23, minute=55), id="daily_backup", replace_existing=True)
    scheduler.add_job(send_no_review_alert, CronTrigger(hour=21, minute=0), id="no_review_alert", replace_existing=True)
    scheduler.add_job(morning_risk_check, CronTrigger(hour=8, minute=45), id="morning_risk", replace_existing=True)
    scheduler.start()
    logger.info("Scheduler started")


async def morning_risk_check():
    """Check risk score in the morning and send alert if high."""
    try:
        from app.routes.analytics import daily_risk_score
        result = await daily_risk_score()
        if result["score"] >= 50:
            await send_risk_alert(result["score"], result["level"], result["factors"])
            logger.info(f"Risk alert sent: score={result['score']}")
    except Exception as e:
        logger.error(f"Morning risk check failed: {e}")
