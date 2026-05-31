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

    # Check consecutive loss streak and send alert
    if pnl is not None and pnl < 0:
        await _check_loss_streak_alert(webhook)


async def _check_loss_streak_alert(webhook: str):
    """Send alert if consecutive loss days >= 3."""
    from datetime import timedelta
    db = await get_db()
    try:
        today = date.today()
        streak = 0
        for i in range(7):
            d = (today - timedelta(days=i)).isoformat()
            cursor = await db.execute(
                "SELECT COALESCE(SUM(pnl), 0) as dp FROM reviews WHERE trade_date = ? AND pnl IS NOT NULL", (d,)
            )
            row = await cursor.fetchone()
            if row["dp"] < 0:
                streak += 1
            else:
                break
    finally:
        await db.close()

    if streak >= 3:
        title = "🚨 连亏预警"
        body = f"**你已经连续 {streak} 天亏损！**\n\n请立即停下来审视：\n- 是否在报复性交易？\n- 是否偏离了计划？\n- 是否需要休息一天？\n\n**连亏时最危险的不是亏损本身，而是你试图一把回本的冲动。**"
        await send_feishu_card(webhook, title, body)


async def send_plan_incomplete_alert():
    """Send alert if today's plans are not all completed by end of day."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT value FROM sys_config WHERE key = 'feishu_webhook'")
        row = await cursor.fetchone()
        webhook = row["value"] if row else ""
        if not webhook:
            return

        today = date.today().isoformat()
        cursor = await db.execute(
            "SELECT content FROM plans WHERE trade_date = ? AND plan_type = 'today' AND done = 0", (today,)
        )
        incomplete = [row["content"] for row in await cursor.fetchall()]
        if not incomplete:
            return

        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM reviews WHERE trade_date = ?", (today,)
        )
        has_review = (await cursor.fetchone())["cnt"] > 0
    finally:
        await db.close()

    title = "📋 计划未完成提醒"
    lines = [f"今日有 **{len(incomplete)}** 条计划未勾选完成："]
    for p in incomplete[:5]:
        lines.append(f"- {p}")
    if not has_review:
        lines.append("\n⚠️ 今日也尚未复盘，请尽快完成。")
    await send_feishu_card(webhook, title, "\n".join(lines))


async def send_big_pnl_alert(pnl: float):
    """Send alert for unusually large PnL (both win and loss)."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT value FROM sys_config WHERE key = 'feishu_webhook'")
        row = await cursor.fetchone()
        webhook = row["value"] if row else ""
        if not webhook:
            return

        # Calculate average absolute PnL
        cursor = await db.execute(
            "SELECT AVG(ABS(pnl)) as avg_pnl FROM reviews WHERE pnl IS NOT NULL AND pnl != 0"
        )
        row = await cursor.fetchone()
        avg = row["avg_pnl"] if row["avg_pnl"] else 0
    finally:
        await db.close()

    if avg == 0:
        return

    # Alert if PnL is > 3x average
    if abs(pnl) > avg * 3:
        if pnl > 0:
            title = "💰 大额盈利提醒"
            body = f"今日盈利 **+{pnl}**，是平均水平的 **{abs(pnl)/avg:.1f}x**。\n\n⚠️ 大赚之后最容易犯的错误：\n- 膨胀加仓\n- 放松纪律\n- 觉得自己无敌\n\n**保持冷静，明天按计划执行。**"
        else:
            title = "💸 大额亏损预警"
            body = f"今日亏损 **{pnl}**，是平均水平的 **{abs(pnl)/avg:.1f}x**。\n\n🛑 请立即检查：\n- 是否止损失效？\n- 是否仓位过重？\n- 是否需要暂停交易？\n\n**保护本金是第一优先级。**"
        await send_feishu_card(webhook, title, body)
