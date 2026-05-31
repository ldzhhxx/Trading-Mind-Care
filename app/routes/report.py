"""Deep Report - comprehensive AI analysis report (v7.0)."""
import json
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from datetime import date, timedelta
from app.database import get_db
from app.llm import call_llm_stream

router = APIRouter(prefix="/api/report", tags=["report"])

REPORT_SYSTEM = """你是一位资深交易心理分析师，正在为交易员撰写深度分析报告。

报告结构（严格按此格式）：
## 📊 数据概览
关键数字汇总

## 🎯 核心发现
最重要的 2-3 个发现

## ⚠️ 风险预警
当前最需要警惕的问题

## 📈 进步与退步
对比分析

## 🔧 行动建议
具体、可执行的 3-5 条建议（按优先级排序）

## 💡 教练寄语
一句话总结

要求：数据驱动、尖锐直接、不说废话。500字以内。"""


@router.post("/weekly-deep")
async def generate_weekly_deep_report():
    """生成每周深度分析报告."""
    today = date.today()
    this_week_start = today - timedelta(days=today.weekday())
    last_week_start = this_week_start - timedelta(days=7)

    db = await get_db()
    try:
        # This week reviews
        cursor = await db.execute(
            "SELECT trade_date, pnl, mood, emotion_log FROM reviews WHERE trade_date >= ? ORDER BY trade_date",
            (this_week_start.isoformat(),)
        )
        this_week = [dict(r) for r in await cursor.fetchall()]

        # Last week reviews
        cursor = await db.execute(
            "SELECT trade_date, pnl, mood FROM reviews WHERE trade_date >= ? AND trade_date < ?",
            (last_week_start.isoformat(), this_week_start.isoformat())
        )
        last_week = [dict(r) for r in await cursor.fetchall()]

        # Vulnerabilities
        cursor = await db.execute(
            "SELECT tag, weight, hit_count, last_hit_at FROM vulnerability_matrix WHERE hit_count > 0 ORDER BY weight DESC LIMIT 8"
        )
        vulns = [dict(r) for r in await cursor.fetchall()]

        # Plan execution
        cursor = await db.execute(
            "SELECT COUNT(*) as total, SUM(done) as completed FROM plans WHERE trade_date >= ? AND plan_type='today'",
            (this_week_start.isoformat(),)
        )
        plan_row = await cursor.fetchone()
        plan_rate = (plan_row["completed"] or 0) / plan_row["total"] * 100 if plan_row["total"] else 0

        # Rules
        cursor = await db.execute("SELECT rule, category FROM trade_rules WHERE active = 1")
        rules = [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()

    # Build comprehensive context
    def week_stats(reviews):
        if not reviews:
            return "无数据"
        pnls = [r["pnl"] for r in reviews if r["pnl"] is not None]
        moods = [r["mood"] for r in reviews if r["mood"]]
        total = sum(pnls)
        wins = sum(1 for p in pnls if p > 0)
        return f"交易{len(reviews)}天, 盈亏{total:+.0f}, 胜率{wins}/{len(pnls)}, 平均情绪{sum(moods)/len(moods):.1f}/5" if pnls else f"交易{len(reviews)}天, 未记录盈亏"

    emotions = "\n".join(f"- {r['trade_date']}: {r['emotion_log'][:80]}" for r in this_week[:5])
    vulns_text = "\n".join(f"- {v['tag']} (权重{v['weight']:.1f}, 触发{v['hit_count']}次, 最近{v['last_hit_at'] or '未知'})" for v in vulns)

    user_msg = f"""【本周】{week_stats(this_week)}
【上周】{week_stats(last_week)}
【计划执行率】{plan_rate:.0f}%
【活跃弱点】
{vulns_text or '无'}
【交易纪律】共{len(rules)}条规则
【本周情绪摘要】
{emotions or '无记录'}

请生成本周深度分析报告。"""

    messages = [
        {"role": "system", "content": REPORT_SYSTEM},
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


@router.post("/monthly-deep")
async def generate_monthly_deep_report():
    """生成每月深度分析报告."""
    today = date.today()
    month_start = today.replace(day=1)
    last_month_start = (month_start - timedelta(days=1)).replace(day=1)

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT trade_date, pnl, mood, emotion_log FROM reviews WHERE trade_date >= ? ORDER BY trade_date",
            (month_start.isoformat(),)
        )
        this_month = [dict(r) for r in await cursor.fetchall()]

        cursor = await db.execute(
            "SELECT trade_date, pnl, mood FROM reviews WHERE trade_date >= ? AND trade_date < ?",
            (last_month_start.isoformat(), month_start.isoformat())
        )
        last_month = [dict(r) for r in await cursor.fetchall()]

        cursor = await db.execute(
            "SELECT tag, weight, hit_count FROM vulnerability_matrix WHERE hit_count > 0 ORDER BY weight DESC"
        )
        vulns = [dict(r) for r in await cursor.fetchall()]

        cursor = await db.execute(
            "SELECT COUNT(*) as total, SUM(done) as completed FROM plans WHERE trade_date >= ? AND plan_type='today'",
            (month_start.isoformat(),)
        )
        plan_row = await cursor.fetchone()
        plan_rate = (plan_row["completed"] or 0) / plan_row["total"] * 100 if plan_row["total"] else 0

        # Monthly PnL curve
        cursor = await db.execute(
            "SELECT trade_date, SUM(pnl) as daily_pnl FROM reviews WHERE trade_date >= ? AND pnl IS NOT NULL GROUP BY trade_date ORDER BY trade_date",
            (month_start.isoformat(),)
        )
        daily_pnls = [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()

    def month_stats(reviews):
        if not reviews:
            return "无数据"
        pnls = [r["pnl"] for r in reviews if r["pnl"] is not None]
        if not pnls:
            return f"交易{len(reviews)}天, 未记录盈亏"
        total = sum(pnls)
        wins = sum(1 for p in pnls if p > 0)
        max_dd = 0
        peak = 0
        cumulative = 0
        for p in pnls:
            cumulative += p
            peak = max(peak, cumulative)
            max_dd = min(max_dd, cumulative - peak)
        return f"交易{len(pnls)}天, 盈亏{total:+.0f}, 胜率{wins}/{len(pnls)}({wins/len(pnls)*100:.0f}%), 最大回撤{max_dd:.0f}"

    pnl_curve = ", ".join(f"{r['trade_date'][-5:]}:{r['daily_pnl']:+.0f}" for r in daily_pnls[-15:])
    vulns_text = ", ".join(f"{v['tag']}({v['weight']:.1f})" for v in vulns[:10])

    user_msg = f"""【本月】{month_stats(this_month)}
【上月】{month_stats(last_month)}
【计划执行率】{plan_rate:.0f}%
【弱点矩阵】{vulns_text or '无'}
【盈亏曲线(近15天)】{pnl_curve or '无'}

请生成本月深度分析报告，重点分析月度趋势和长期改善方向。"""

    messages = [
        {"role": "system", "content": REPORT_SYSTEM},
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
