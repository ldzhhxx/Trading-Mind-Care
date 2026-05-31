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


def _weight_bar(weight: float, max_weight: float = 5.0) -> str:
    """Generate emoji weight bar."""
    filled = min(5, int(weight / max_weight * 5))
    return "🟥" * filled + "⬜" * (5 - filled)


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

        # Yesterday's review summary
        from datetime import timedelta
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        cursor = await db.execute(
            "SELECT pnl, ai_critique FROM reviews WHERE trade_date = ? ORDER BY created_at DESC LIMIT 1",
            (yesterday,)
        )
        yesterday_review = await cursor.fetchone()
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
        lines.append("\n**⚠️ 弱点 Top 3**")
        for v in vulns:
            bar = _weight_bar(v["weight"])
            lines.append(f"- {v['tag']} {bar} ({v['weight']:.1f})")

    if yesterday_review:
        lines.append("\n**📝 昨日复盘摘要**")
        pnl = yesterday_review["pnl"]
        if pnl is not None:
            lines.append(f"- 盈亏: {'🟢' if pnl >= 0 else '🔴'} {'+' if pnl >= 0 else ''}{pnl}")
        critique = yesterday_review["ai_critique"] or ""
        if critique:
            lines.append(f"- AI: {critique[:100]}{'...' if len(critique) > 100 else ''}")

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


async def send_review_notification(pnl, critique: str, new_weaknesses: list[str]):
    """Send notification after review completion."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT value FROM sys_config WHERE key = 'feishu_webhook'")
        row = await cursor.fetchone()
        webhook = row["value"] if row else ""
        if not webhook:
            return
    finally:
        await db.close()

    title = "🔥 复盘完成通知"
    lines = []
    if pnl is not None:
        lines.append(f"**盈亏：** {'🟢' if pnl >= 0 else '🔴'} {'+' if pnl >= 0 else ''}{pnl}")
    if critique:
        lines.append(f"**AI 拷打摘要：** {critique[:150]}{'...' if len(critique) > 150 else ''}")
    if new_weaknesses:
        lines.append(f"**新提取弱点：** {', '.join(new_weaknesses)}")
    if not lines:
        lines.append("复盘已完成。")

    await send_feishu_card(webhook, title, "\n".join(lines))
