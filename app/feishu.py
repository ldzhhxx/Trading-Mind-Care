"""Feishu webhook notification."""
import httpx
from datetime import date
from app.database import get_db


async def send_feishu_card(webhook_url: str, title: str, content: str) -> bool:
    """Send a rich text card to Feishu. Returns True on success."""
    if not webhook_url:
        return False
    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {"title": {"tag": "plain_text", "content": title}},
            "elements": [{"tag": "markdown", "content": content}],
        },
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook_url, json=payload)
            return resp.status_code == 200
    except Exception:
        return False


async def build_daily_message() -> tuple[str, str]:
    """Build daily notification content. Returns (title, markdown_body)."""
    today = date.today().isoformat()
    db = await get_db()
    try:
        # Today's plans
        cursor = await db.execute(
            "SELECT content FROM plans WHERE trade_date = ?", (today,)
        )
        plans = [row["content"] for row in await cursor.fetchall()]

        # Top vulnerabilities
        cursor = await db.execute(
            "SELECT tag, weight FROM vulnerability_matrix WHERE weight >= 1.5 ORDER BY weight DESC LIMIT 3"
        )
        vulns = await cursor.fetchall()
    finally:
        await db.close()

    title = f"🧠 Trading Mind Care - {today}"
    lines = ["**📋 今日计划**"]
    if plans:
        for p in plans:
            lines.append(f"- {p}")
    else:
        lines.append("- （未设置计划）")

    if vulns:
        lines.append("\n**⚠️ 高频弱点警告**")
        for v in vulns:
            lines.append(f"- 🔴 {v['tag']}（权重 {v['weight']:.1f}）")

    lines.append("\n---\n**🛑 防断手警示：严格执行计划，不要让情绪接管你的账户。**")
    return title, "\n".join(lines)


async def send_daily_notification():
    """Send daily notification if not already sent today."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT value FROM sys_config WHERE key = 'last_notify_date'")
        row = await cursor.fetchone()
        today = date.today().isoformat()
        if row and row["value"] == today:
            return  # Already sent today

        cursor = await db.execute("SELECT value FROM sys_config WHERE key = 'feishu_webhook'")
        row = await cursor.fetchone()
        webhook = row["value"] if row else ""
        if not webhook:
            return

        title, body = await build_daily_message()
        success = await send_feishu_card(webhook, title, body)
        if success:
            await db.execute(
                "INSERT OR REPLACE INTO sys_config (key, value) VALUES ('last_notify_date', ?)",
                (today,),
            )
            await db.commit()
    finally:
        await db.close()
