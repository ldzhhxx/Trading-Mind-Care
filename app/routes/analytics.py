"""Advanced analytics routes - deep data analysis for v5.0."""
import json
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from datetime import date, timedelta
from app.database import get_db
from app.llm import call_llm_stream

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/pnl-distribution")
async def pnl_distribution():
    """盈亏分布分析：盈利日 vs 亏损日特征对比."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT trade_date, SUM(pnl) as daily_pnl, AVG(mood) as avg_mood "
            "FROM reviews WHERE pnl IS NOT NULL GROUP BY trade_date ORDER BY trade_date"
        )
        rows = await cursor.fetchall()
        win_days, loss_days = [], []
        for r in rows:
            entry = {"date": r["trade_date"], "pnl": r["daily_pnl"], "mood": r["avg_mood"]}
            if r["daily_pnl"] >= 0:
                win_days.append(entry)
            else:
                loss_days.append(entry)

        # Plan execution rate on win vs loss days
        win_plan_rate = await _plan_rate_for_dates(db, [d["date"] for d in win_days])
        loss_plan_rate = await _plan_rate_for_dates(db, [d["date"] for d in loss_days])

        win_avg_mood = sum(d["mood"] or 3 for d in win_days) / len(win_days) if win_days else 0
        loss_avg_mood = sum(d["mood"] or 3 for d in loss_days) / len(loss_days) if loss_days else 0

        return {
            "win_days_count": len(win_days),
            "loss_days_count": len(loss_days),
            "win_avg_pnl": sum(d["pnl"] for d in win_days) / len(win_days) if win_days else 0,
            "loss_avg_pnl": sum(d["pnl"] for d in loss_days) / len(loss_days) if loss_days else 0,
            "win_avg_mood": round(win_avg_mood, 2),
            "loss_avg_mood": round(loss_avg_mood, 2),
            "win_plan_rate": round(win_plan_rate, 1),
            "loss_plan_rate": round(loss_plan_rate, 1),
            "distribution": [{"pnl": d["pnl"], "date": d["date"]} for d in rows],
        }
    finally:
        await db.close()


@router.get("/emotion-correlation")
async def emotion_correlation():
    """情绪与盈亏的深度相关性分析."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT mood, pnl, trade_date FROM reviews WHERE mood IS NOT NULL AND pnl IS NOT NULL ORDER BY trade_date"
        )
        rows = [dict(r) for r in await cursor.fetchall()]
        if not rows:
            return {"correlation": 0, "data": [], "insight": "数据不足"}

        # Group by mood
        mood_groups = {}
        for r in rows:
            mood_groups.setdefault(r["mood"], []).append(r["pnl"])

        mood_stats = []
        for mood in sorted(mood_groups.keys()):
            pnls = mood_groups[mood]
            wins = sum(1 for p in pnls if p > 0)
            mood_stats.append({
                "mood": mood,
                "count": len(pnls),
                "avg_pnl": round(sum(pnls) / len(pnls), 2),
                "win_rate": round(wins / len(pnls) * 100, 1),
                "total_pnl": round(sum(pnls), 2),
            })

        # Simple correlation coefficient
        n = len(rows)
        if n < 3:
            corr = 0
        else:
            moods = [r["mood"] for r in rows]
            pnls = [r["pnl"] for r in rows]
            mean_m = sum(moods) / n
            mean_p = sum(pnls) / n
            cov = sum((moods[i] - mean_m) * (pnls[i] - mean_p) for i in range(n)) / n
            std_m = (sum((m - mean_m) ** 2 for m in moods) / n) ** 0.5
            std_p = (sum((p - mean_p) ** 2 for p in pnls) / n) ** 0.5
            corr = round(cov / (std_m * std_p), 3) if std_m > 0 and std_p > 0 else 0

        insight = "情绪与盈亏正相关" if corr > 0.2 else "情绪与盈亏负相关" if corr < -0.2 else "情绪与盈亏无明显相关"
        return {"correlation": corr, "mood_stats": mood_stats, "insight": insight, "sample_size": n}
    finally:
        await db.close()


@router.get("/plan-correlation")
async def plan_correlation():
    """计划执行率与盈亏的相关性分析."""
    db = await get_db()
    try:
        # Get dates with both plans and reviews
        cursor = await db.execute(
            "SELECT DISTINCT r.trade_date, SUM(r.pnl) as daily_pnl "
            "FROM reviews r WHERE r.pnl IS NOT NULL GROUP BY r.trade_date"
        )
        review_days = {r["trade_date"]: r["daily_pnl"] for r in await cursor.fetchall()}

        data_points = []
        for td, pnl in review_days.items():
            cursor = await db.execute(
                "SELECT COUNT(*) as total, SUM(done) as completed FROM plans WHERE trade_date = ? AND plan_type='today'",
                (td,)
            )
            pr = await cursor.fetchone()
            if pr["total"] > 0:
                rate = (pr["completed"] or 0) / pr["total"] * 100
                data_points.append({"date": td, "plan_rate": round(rate, 1), "pnl": pnl})

        if not data_points:
            return {"correlation": 0, "data": [], "insight": "数据不足"}

        # Group by execution rate ranges
        high_exec = [d for d in data_points if d["plan_rate"] >= 80]
        mid_exec = [d for d in data_points if 40 <= d["plan_rate"] < 80]
        low_exec = [d for d in data_points if d["plan_rate"] < 40]

        def avg_pnl(lst):
            return round(sum(d["pnl"] for d in lst) / len(lst), 2) if lst else 0

        return {
            "high_exec": {"count": len(high_exec), "avg_pnl": avg_pnl(high_exec)},
            "mid_exec": {"count": len(mid_exec), "avg_pnl": avg_pnl(mid_exec)},
            "low_exec": {"count": len(low_exec), "avg_pnl": avg_pnl(low_exec)},
            "data": data_points[-30:],
            "insight": f"高执行率({len(high_exec)}天)平均盈亏{avg_pnl(high_exec)}，低执行率({len(low_exec)}天)平均盈亏{avg_pnl(low_exec)}",
        }
    finally:
        await db.close()


@router.get("/weakness-timeline")
async def weakness_timeline():
    """弱点出现频率的时间分布."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT tag, last_hit_at, hit_count, weight FROM vulnerability_matrix WHERE hit_count > 0 ORDER BY weight DESC LIMIT 10"
        )
        vulns = [dict(r) for r in await cursor.fetchall()]

        # Get review dates with extracted weaknesses (from AI critique content)
        cursor = await db.execute(
            "SELECT trade_date, ai_critique FROM reviews WHERE ai_critique IS NOT NULL ORDER BY trade_date DESC LIMIT 60"
        )
        reviews = await cursor.fetchall()

        # Map weakness mentions by week
        weekly_hits = {}
        for v in vulns:
            tag = v["tag"]
            for r in reviews:
                if tag in (r["ai_critique"] or ""):
                    week = r["trade_date"][:7]  # YYYY-MM
                    weekly_hits.setdefault(tag, {}).setdefault(week, 0)
                    weekly_hits[tag][week] += 1

        return {"vulnerabilities": vulns, "timeline": weekly_hits}
    finally:
        await db.close()


@router.get("/session-analysis")
async def session_analysis():
    """最佳交易时段分析（基于复盘提交时间推断）."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT CAST(strftime('%H', created_at) AS INTEGER) as hour, "
            "COUNT(*) as cnt, AVG(pnl) as avg_pnl, SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins "
            "FROM reviews WHERE pnl IS NOT NULL GROUP BY hour ORDER BY hour"
        )
        rows = [dict(r) for r in await cursor.fetchall()]

        # Group into sessions
        morning = [r for r in rows if 6 <= r["hour"] < 12]
        afternoon = [r for r in rows if 12 <= r["hour"] < 18]
        evening = [r for r in rows if r["hour"] >= 18 or r["hour"] < 6]

        def session_stats(session):
            if not session:
                return {"count": 0, "avg_pnl": 0, "win_rate": 0}
            total = sum(s["cnt"] for s in session)
            wins = sum(s["wins"] for s in session)
            avg = sum(s["avg_pnl"] * s["cnt"] for s in session) / total if total else 0
            return {"count": total, "avg_pnl": round(avg, 2), "win_rate": round(wins / total * 100, 1) if total else 0}

        return {
            "morning": session_stats(morning),
            "afternoon": session_stats(afternoon),
            "evening": session_stats(evening),
            "hourly": rows,
        }
    finally:
        await db.close()


@router.get("/periodicity")
async def pnl_periodicity():
    """盈亏周期性分析：按周、按月的表现规律."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT trade_date, SUM(pnl) as daily_pnl FROM reviews WHERE pnl IS NOT NULL GROUP BY trade_date ORDER BY trade_date"
        )
        rows = [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()

    if not rows:
        return {"weekly": [], "monthly": [], "insight": "数据不足"}

    from collections import defaultdict
    # Weekly aggregation (ISO week)
    weekly = defaultdict(lambda: {"pnl": 0, "days": 0})
    for r in rows:
        d = date.fromisoformat(r["trade_date"])
        week_key = f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}"
        weekly[week_key]["pnl"] += r["daily_pnl"]
        weekly[week_key]["days"] += 1

    weekly_list = [{"week": k, "pnl": round(v["pnl"], 1), "days": v["days"]} for k, v in sorted(weekly.items())][-12:]

    # Monthly aggregation
    monthly = defaultdict(lambda: {"pnl": 0, "days": 0})
    for r in rows:
        month_key = r["trade_date"][:7]
        monthly[month_key]["pnl"] += r["daily_pnl"]
        monthly[month_key]["days"] += 1

    monthly_list = [{"month": k, "pnl": round(v["pnl"], 1), "days": v["days"]} for k, v in sorted(monthly.items())[-6:]]

    # Weekday pattern
    dow_pnl = defaultdict(list)
    for r in rows:
        d = date.fromisoformat(r["trade_date"])
        dow_pnl[d.weekday()].append(r["daily_pnl"])

    dow_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
    weekday_pattern = []
    for i in range(7):
        if dow_pnl[i]:
            avg = sum(dow_pnl[i]) / len(dow_pnl[i])
            weekday_pattern.append({"day": dow_names[i], "avg_pnl": round(avg, 1), "count": len(dow_pnl[i])})

    # Find best/worst periods
    best_week = max(weekly_list, key=lambda x: x["pnl"]) if weekly_list else None
    worst_week = min(weekly_list, key=lambda x: x["pnl"]) if weekly_list else None

    return {
        "weekly": weekly_list,
        "monthly": monthly_list,
        "weekday_pattern": weekday_pattern,
        "best_week": best_week,
        "worst_week": worst_week,
    }


@router.post("/ai-week-compare")
async def ai_week_compare():
    """AI 对比本周 vs 上周的表现变化."""
    today = date.today()
    this_week_start = (today - timedelta(days=today.weekday())).isoformat()
    last_week_start = (today - timedelta(days=today.weekday() + 7)).isoformat()

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT trade_date, pnl, mood, emotion_log FROM reviews WHERE trade_date >= ? ORDER BY trade_date",
            (last_week_start,)
        )
        all_reviews = [dict(r) for r in await cursor.fetchall()]
        this_week = [r for r in all_reviews if r["trade_date"] >= this_week_start]
        last_week = [r for r in all_reviews if r["trade_date"] < this_week_start]

        cursor = await db.execute(
            "SELECT tag, weight FROM vulnerability_matrix ORDER BY weight DESC LIMIT 5"
        )
        vulns = [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()

    def week_summary(reviews):
        if not reviews:
            return "无数据"
        pnl = sum(r["pnl"] or 0 for r in reviews)
        moods = [r["mood"] for r in reviews if r["mood"]]
        avg_mood = sum(moods) / len(moods) if moods else 0
        return f"交易{len(reviews)}天, 盈亏{pnl:.1f}, 平均情绪{avg_mood:.1f}/5"

    user_msg = f"""【上周】{week_summary(last_week)}
【本周】{week_summary(this_week)}
【当前弱点TOP5】{', '.join(f"{v['tag']}({v['weight']:.1f})" for v in vulns)}

请对比分析本周vs上周的变化，指出进步和退步，给出下周建议。200字以内。"""

    messages = [
        {"role": "system", "content": "你是交易心理教练，擅长对比分析交易员的周度表现变化。尖锐、数据驱动。"},
        {"role": "user", "content": user_msg},
    ]

    async def stream():
        try:
            async for chunk in call_llm_stream(messages):
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post("/ai-danger-signals")
async def ai_danger_signals():
    """AI 识别即将到来的危险信号."""
    today = date.today()
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT trade_date, pnl, mood, emotion_log FROM reviews ORDER BY trade_date DESC LIMIT 10"
        )
        recent = [dict(r) for r in await cursor.fetchall()]
        cursor = await db.execute(
            "SELECT tag, weight, hit_count FROM vulnerability_matrix WHERE weight >= 1.5 ORDER BY weight DESC LIMIT 5"
        )
        vulns = [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()

    pnl_list = [r["pnl"] for r in recent if r["pnl"] is not None]
    consecutive_wins = 0
    for p in pnl_list:
        if p > 0:
            consecutive_wins += 1
        else:
            break

    user_msg = f"""【近10次交易盈亏】{', '.join(f"{p:.1f}" for p in pnl_list[:10])}
【连续盈利次数】{consecutive_wins}
【活跃弱点】{', '.join(f"{v['tag']}(权重{v['weight']:.1f},触发{v['hit_count']}次)" for v in vulns)}
【近期情绪摘要】{'; '.join(r['emotion_log'][:50] for r in recent[:3])}

请识别当前是否存在危险信号（如连续盈利后的膨胀期、情绪波动加大、弱点权重上升等），给出预警。150字以内。"""

    messages = [
        {"role": "system", "content": "你是交易心理教练，专门识别交易员即将犯错的前兆信号。你的预警要具体、可操作。"},
        {"role": "user", "content": user_msg},
    ]

    async def stream():
        try:
            async for chunk in call_llm_stream(messages):
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post("/ai-plan-check")
async def ai_plan_check(content: dict):
    """AI 识别计划中的模糊表述并提醒用户具体化."""
    plan_text = content.get("content", "")
    if not plan_text.strip():
        return {"suggestions": []}

    messages = [
        {"role": "system", "content": """你是交易计划审核专家。分析交易计划，找出模糊、不可执行的表述。
返回严格JSON数组，每个元素：{"issue": "模糊点", "suggestion": "具体化建议"}
如果计划已经足够具体，返回空数组 []。只返回JSON。"""},
        {"role": "user", "content": plan_text},
    ]

    from app.llm import call_llm
    try:
        raw = await call_llm(messages)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
        suggestions = json.loads(raw)
        return {"suggestions": suggestions if isinstance(suggestions, list) else []}
    except Exception:
        return {"suggestions": []}


@router.post("/ai-weakness-deep")
async def ai_weakness_deep_analysis():
    """AI 对弱点矩阵进行深度分析，找出弱点之间的关联."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT tag, weight, hit_count, last_hit_at, category FROM vulnerability_matrix WHERE hit_count > 0 ORDER BY weight DESC"
        )
        vulns = [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()

    if not vulns:
        async def empty():
            yield f"data: {json.dumps({'chunk': '暂无弱点数据，请先完成几次复盘。'})}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(empty(), media_type="text/event-stream")

    vulns_text = "\n".join(f"- {v['tag']} (权重{v['weight']:.2f}, 触发{v['hit_count']}次, 最近{v['last_hit_at'] or '未知'})" for v in vulns)

    messages = [
        {"role": "system", "content": "你是交易心理分析专家，擅长发现弱点之间的深层关联和因果链。分析弱点矩阵，找出：1.哪些弱点互为因果 2.哪些弱点总是一起出现 3.根源性弱点是什么 4.改善优先级建议。300字以内。"},
        {"role": "user", "content": f"当前弱点矩阵：\n{vulns_text}"},
    ]

    async def stream():
        try:
            async for chunk in call_llm_stream(messages):
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


async def _plan_rate_for_dates(db, dates: list[str]) -> float:
    if not dates:
        return 0
    placeholders = ",".join("?" * len(dates))
    cursor = await db.execute(
        f"SELECT COUNT(*) as total, SUM(done) as completed FROM plans WHERE trade_date IN ({placeholders}) AND plan_type='today'",
        dates
    )
    row = await cursor.fetchone()
    if row["total"] == 0:
        return 0
    return (row["completed"] or 0) / row["total"] * 100


@router.post("/ai-behavior-patterns")
async def ai_behavior_patterns():
    """AI 识别用户的行为模式（如每周一容易冲动、连赢后加仓等）."""
    from collections import defaultdict
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT trade_date, pnl, mood, emotion_log FROM reviews WHERE pnl IS NOT NULL ORDER BY trade_date DESC LIMIT 60"
        )
        reviews = [dict(r) for r in await cursor.fetchall()]
        cursor = await db.execute(
            "SELECT tag, weight, hit_count FROM vulnerability_matrix WHERE hit_count > 0 ORDER BY weight DESC LIMIT 10"
        )
        vulns = [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()

    if len(reviews) < 5:
        async def empty():
            yield f"data: {json.dumps({'chunk': '数据不足（至少需要5次复盘），请继续积累。'})}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(empty(), media_type="text/event-stream")

    weekday_data = defaultdict(list)
    for r in reviews:
        dow = date.fromisoformat(r["trade_date"]).strftime("%A")
        weekday_data[dow].append(r["pnl"])
    weekday_summary = ", ".join(f"{d}: {len(v)}笔 avg={sum(v)/len(v):.1f}" for d, v in weekday_data.items())

    user_msg = f"""【近60次交易】共{len(reviews)}笔
【星期分布】{weekday_summary}
【弱点TOP10】{', '.join(f"{v['tag']}({v['hit_count']}次)" for v in vulns)}
【近期情绪】{'; '.join(r['emotion_log'][:60] for r in reviews[:5])}

请分析行为模式：1.哪些日子容易犯错 2.连赢/连亏后行为变化 3.情绪与决策关联 4.给出3-5个具体模式+改善建议。300字以内。"""

    messages = [
        {"role": "system", "content": "你是交易行为分析专家，擅长从数据中识别行为模式。分析要具体、数据驱动。"},
        {"role": "user", "content": user_msg},
    ]

    async def stream():
        try:
            async for chunk in call_llm_stream(messages):
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get("/trading-style")
async def trading_style_analysis():
    """交易风格分析：激进 vs 保守 + 风险管理评估."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT pnl, trade_date FROM reviews WHERE pnl IS NOT NULL ORDER BY trade_date"
        )
        rows = [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()

    if not rows:
        return {"style": "unknown", "metrics": {}, "risk_assessment": {}}

    pnls = [r["pnl"] for r in rows]
    abs_pnls = [abs(p) for p in pnls]
    avg_abs = sum(abs_pnls) / len(abs_pnls)
    max_win = max(pnls)
    max_loss = min(pnls)
    mean_pnl = sum(pnls) / len(pnls)
    volatility = (sum((p - mean_pnl)**2 for p in pnls) / len(pnls)) ** 0.5 if len(pnls) > 1 else 0

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0
    risk_reward = avg_win / avg_loss if avg_loss > 0 else 0

    aggression_score = min(100, int((volatility / (avg_abs + 1)) * 50 + (abs(max_loss) / (avg_abs + 1)) * 20))
    style = "激进型" if aggression_score > 70 else "均衡型" if aggression_score > 40 else "保守型"

    # Risk management assessment
    # Stop-loss discipline: % of losses that are within 1.5x avg loss
    controlled_losses = sum(1 for p in losses if abs(p) <= avg_loss * 1.5) if losses else 0
    stop_loss_rate = round(controlled_losses / len(losses) * 100, 1) if losses else 100

    # Position sizing: % of trades within 2x avg absolute PnL
    controlled_trades = sum(1 for p in pnls if abs(p) <= avg_abs * 2)
    position_control_rate = round(controlled_trades / len(pnls) * 100, 1) if pnls else 100

    # Consecutive loss recovery: avg PnL after 2+ consecutive losses
    recovery_pnls = []
    for i in range(2, len(pnls)):
        if pnls[i-1] < 0 and pnls[i-2] < 0:
            recovery_pnls.append(pnls[i])
    avg_recovery = round(sum(recovery_pnls) / len(recovery_pnls), 1) if recovery_pnls else 0

    return {
        "style": style,
        "aggression_score": aggression_score,
        "metrics": {
            "avg_abs_pnl": round(avg_abs, 1),
            "max_win": round(max_win, 1),
            "max_loss": round(max_loss, 1),
            "volatility": round(volatility, 1),
            "risk_reward": round(risk_reward, 2),
            "win_count": len(wins),
            "loss_count": len(losses),
            "total_trades": len(pnls),
        },
        "risk_assessment": {
            "stop_loss_rate": stop_loss_rate,
            "position_control_rate": position_control_rate,
            "avg_recovery_pnl": avg_recovery,
            "risk_score": round((stop_loss_rate + position_control_rate) / 2, 1),
        },
    }


@router.post("/ai-generate-rules")
async def ai_generate_rules():
    """AI 生成个性化的交易纪律清单."""

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT tag, weight, hit_count FROM vulnerability_matrix WHERE weight >= 1.0 ORDER BY weight DESC LIMIT 10"
        )
        vulns = [dict(r) for r in await cursor.fetchall()]
        cursor = await db.execute("SELECT rule, category FROM trade_rules WHERE active = 1")
        existing_rules = [dict(r) for r in await cursor.fetchall()]
        cursor = await db.execute(
            "SELECT emotion_log FROM reviews ORDER BY created_at DESC LIMIT 5"
        )
        recent_emotions = [r["emotion_log"][:100] for r in await cursor.fetchall()]
    finally:
        await db.close()

    vulns_text = "\n".join(f"- {v['tag']} (权重{v['weight']:.1f}, 触发{v['hit_count']}次)" for v in vulns) or "暂无"
    rules_text = "\n".join(f"- [{r['category']}] {r['rule']}" for r in existing_rules) or "暂无"
    emotions_text = "\n".join(f"- {e}" for e in recent_emotions) or "暂无"

    messages = [
        {"role": "system", "content": """你是交易纪律制定专家。根据交易员的弱点和历史行为，生成个性化的交易纪律清单。
返回严格JSON数组，每个元素：{"rule": "具体规则", "category": "风控/纪律/心态", "reason": "为什么需要这条规则"}
规则要具体、可量化、可执行。不要泛泛而谈。5-8条即可。只返回JSON。"""},
        {"role": "user", "content": f"【当前弱点】\n{vulns_text}\n\n【现有规则】\n{rules_text}\n\n【近期倾诉】\n{emotions_text}"},
    ]

    from app.llm import call_llm
    try:
        raw = await call_llm(messages)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
        rules = json.loads(raw)
        return {"rules": rules if isinstance(rules, list) else []}
    except Exception as e:
        return {"rules": [], "error": str(e)}


@router.get("/style-evolution")
async def style_evolution():
    """交易风格演变趋势 — 按月追踪风格变化."""
    from collections import defaultdict
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT trade_date, pnl FROM reviews WHERE pnl IS NOT NULL ORDER BY trade_date"
        )
        rows = [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()

    if len(rows) < 5:
        return {"months": [], "message": "数据不足，至少需要5条记录"}

    # Group by month
    monthly = defaultdict(list)
    for r in rows:
        month = r["trade_date"][:7]
        monthly[month].append(r["pnl"])

    evolution = []
    for month in sorted(monthly.keys()):
        pnls = monthly[month]
        if len(pnls) < 2:
            continue
        mean = sum(pnls) / len(pnls)
        volatility = (sum((p - mean)**2 for p in pnls) / len(pnls)) ** 0.5
        wins = sum(1 for p in pnls if p > 0)
        avg_win = sum(p for p in pnls if p > 0) / wins if wins else 0
        losses = [p for p in pnls if p < 0]
        avg_loss = abs(sum(losses) / len(losses)) if losses else 0
        rr = avg_win / avg_loss if avg_loss > 0 else 0
        aggression = min(100, int(volatility / (abs(mean) + 1) * 50))

        evolution.append({
            "month": month,
            "trades": len(pnls),
            "total_pnl": round(sum(pnls), 1),
            "win_rate": round(wins / len(pnls) * 100, 1),
            "volatility": round(volatility, 1),
            "risk_reward": round(rr, 2),
            "aggression": aggression,
        })

    return {"months": evolution}


@router.get("/mood-trend")
async def mood_trend():
    """情绪趋势 — 追踪情绪随时间的变化."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT trade_date, AVG(mood) as avg_mood, SUM(pnl) as daily_pnl "
            "FROM reviews WHERE mood IS NOT NULL "
            "GROUP BY trade_date ORDER BY trade_date DESC LIMIT 30"
        )
        rows = [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()

    rows.reverse()
    # Detect mood streaks
    if rows:
        low_streak = 0
        for r in reversed(rows):
            if (r["avg_mood"] or 3) <= 2:
                low_streak += 1
            else:
                break
    else:
        low_streak = 0

    return {
        "data": [{"date": r["trade_date"], "mood": round(r["avg_mood"], 1), "pnl": r["daily_pnl"]} for r in rows],
        "low_mood_streak": low_streak,
        "avg_mood": round(sum(r["avg_mood"] for r in rows) / len(rows), 2) if rows else 0,
    }
