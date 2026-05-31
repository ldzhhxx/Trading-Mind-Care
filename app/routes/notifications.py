"""Notification routes (Feishu test)."""
from fastapi import APIRouter
from app.database import get_db
from app.feishu import send_feishu_card, build_daily_message

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.post("/test-feishu")
async def test_feishu():
    db = await get_db()
    try:
        cursor = await db.execute("SELECT value FROM sys_config WHERE key = 'feishu_webhook'")
        row = await cursor.fetchone()
        webhook = row["value"] if row else ""
    finally:
        await db.close()

    if not webhook:
        return {"success": False, "error": "未配置飞书 Webhook"}

    title, body = await build_daily_message()
    success = await send_feishu_card(webhook, title, body)
    return {"success": success, "error": None if success else "发送失败，请检查 Webhook URL"}
