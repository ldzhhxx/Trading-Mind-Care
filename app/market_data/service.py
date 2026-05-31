"""Market data service: caching, analysis, and trade context building."""
from __future__ import annotations
import json
import logging
import asyncio
from datetime import date, timedelta
from typing import Any

from app.database import get_db
from app.market_data.provider import get_market_manager

logger = logging.getLogger(__name__)

# Index mapping by stock code prefix
_INDEX_MAP = {"6": "sh", "0": "sz", "3": "sz", "8": "sh", "4": "sh"}


def _index_for_code(code: str) -> str:
    return _INDEX_MAP.get(code[0], "sh") if code else "sh"


# ── Cache helpers ────────────────────────────────────────────────────────────

async def _cache_get(code: str, data_date: str, data_type: str) -> dict | None:
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT data_json, source FROM market_cache WHERE stock_code=? AND data_date=? AND data_type=?",
            (code, data_date, data_type),
        )
        row = await cur.fetchone()
        if row:
            return {"data": json.loads(row["data_json"]), "source": row["source"], "cached": True}
        return None
    finally:
        await db.close()


async def _cache_set(code: str, data_date: str, data_type: str, data: Any, source: str) -> None:
    db = await get_db()
    try:
        await db.execute(
            """INSERT OR REPLACE INTO market_cache (stock_code, data_date, data_type, data_json, source)
               VALUES (?, ?, ?, ?, ?)""",
            (code, data_date, data_type, json.dumps(data, ensure_ascii=False), source),
        )
        await db.commit()
    except Exception as e:
        logger.warning(f"Cache write failed: {e}")
    finally:
        await db.close()


# ── Core data fetchers ───────────────────────────────────────────────────────

async def get_daily_kline(code: str, start_date: str, end_date: str) -> list[dict]:
    """Fetch daily kline with cache (cache key = end_date for single-day, range for multi)."""
    cache_key = f"{start_date}_{end_date}"
    cached = await _cache_get(code, cache_key, "daily_kline")
    if cached:
        return cached["data"]

    mgr = get_market_manager()
    bars = await mgr.get_daily_kline(code, start_date, end_date)
    if bars:
        await _cache_set(code, cache_key, "daily_kline", bars, "akshare")
    return bars


async def get_stock_info(code: str) -> dict:
    """Fetch stock basic info with weekly cache."""
    today = date.today().strftime("%Y-%m-%d")
    # Use week-start as cache key so it refreshes weekly
    week_start = (date.today() - timedelta(days=date.today().weekday())).strftime("%Y-%m-%d")
    cached = await _cache_get(code, week_start, "stock_info")
    if cached:
        return cached["data"]

    mgr = get_market_manager()
    info = await mgr.get_stock_info(code)
    if info:
        await _cache_set(code, week_start, "stock_info", info, "akshare")
    return info


async def get_index_kline(index_code: str, trade_date: str) -> dict | None:
    cached = await _cache_get(index_code, trade_date, "index_kline")
    if cached:
        return cached["data"]

    mgr = get_market_manager()
    bar = await mgr.get_index_kline(index_code, trade_date)
    if bar:
        await _cache_set(index_code, trade_date, "index_kline", bar, "akshare")
    return bar


async def get_stock_list_cached() -> list[dict]:
    """Return stock list, refreshed daily."""
    today = date.today().strftime("%Y-%m-%d")
    cached = await _cache_get("__all__", today, "stock_list")
    if cached:
        return cached["data"]

    mgr = get_market_manager()
    stocks = await mgr.get_stock_list()
    if stocks:
        await _cache_set("__all__", today, "stock_list", stocks, "akshare")
        # Also update stock_list table for fast name search
        db = await get_db()
        try:
            await db.executemany(
                "INSERT OR REPLACE INTO stock_list (code, name) VALUES (?, ?)",
                [(s["code"], s["name"]) for s in stocks],
            )
            await db.commit()
        finally:
            await db.close()
    return stocks


# ── Analysis functions ───────────────────────────────────────────────────────

def _calc_vwap(bar: dict) -> float:
    """Estimate VWAP from OHLC (simplified: typical price)."""
    return round((bar["high"] + bar["low"] + bar["close"]) / 3, 4)


def calc_slippage(trade_price: float, vwap: float, direction: str) -> dict:
    """Calculate slippage vs VWAP."""
    if vwap == 0:
        return {"slippage_pct": 0.0, "label": "无数据", "detail": "无法计算VWAP"}
    if direction == "buy":
        pct = (trade_price - vwap) / vwap * 100  # positive = paid more
    else:
        pct = (vwap - trade_price) / vwap * 100  # positive = sold cheaper

    abs_pct = abs(pct)
    label = "优秀" if abs_pct < 0.2 else "良好" if abs_pct < 0.5 else "一般" if abs_pct < 1.0 else "较差"
    direction_word = "买贵了" if (direction == "buy" and pct > 0) else \
                     "买便宜了" if (direction == "buy" and pct <= 0) else \
                     "卖便宜了" if (direction == "sell" and pct > 0) else "卖贵了"
    return {
        "slippage_pct": round(pct, 3),
        "vwap": vwap,
        "trade_price": trade_price,
        "label": label,
        "detail": f"成交价{trade_price} vs 均价{vwap:.2f}，滑点{pct:+.2f}%（{direction_word}）",
    }


def eval_timing(trade_price: float, bar: dict, direction: str) -> dict:
    """Score trade timing 0-100 based on position within day's range."""
    high, low = bar.get("high", 0), bar.get("low", 0)
    if high == low:
        return {"score": 50, "label": "无法评估", "detail": "当日无价格波动"}

    rng = high - low
    pos = (trade_price - low) / rng  # 0=low, 1=high

    if direction == "buy":
        # Lower is better for buy
        score = int((1 - pos) * 100)
        if pos < 0.2:
            label, detail = "优秀", f"买在当日低点附近（低点{low:.2f}，高点{high:.2f}）"
        elif pos < 0.4:
            label, detail = "良好", f"买价偏低，时机不错"
        elif pos < 0.6:
            label, detail = "一般", f"买在当日中间位置"
        elif pos < 0.8:
            label, detail = "较差", f"买价偏高，接近当日高点"
        else:
            label, detail = "很差", f"买在当日高点附近（追涨风险高）"
    else:
        # Higher is better for sell
        score = int(pos * 100)
        if pos > 0.8:
            label, detail = "优秀", f"卖在当日高点附近（高点{high:.2f}，低点{low:.2f}）"
        elif pos > 0.6:
            label, detail = "良好", f"卖价偏高，时机不错"
        elif pos > 0.4:
            label, detail = "一般", f"卖在当日中间位置"
        elif pos > 0.2:
            label, detail = "较差", f"卖价偏低，接近当日低点"
        else:
            label, detail = "很差", f"卖在当日低点附近（恐慌卖出风险）"

    return {"score": max(0, min(100, score)), "label": label, "detail": detail}


def compare_with_index(stock_change: float, index_change: float, index_name: str) -> dict:
    alpha = round(stock_change - index_change, 2)
    return {
        "stock_change": round(stock_change, 2),
        "index_change": round(index_change, 2),
        "alpha": alpha,
        "index_name": index_name,
        "label": "跑赢大盘" if alpha > 0 else "跑输大盘" if alpha < 0 else "与大盘持平",
        "detail": f"个股{stock_change:+.2f}% vs {index_name}{index_change:+.2f}%，超额{alpha:+.2f}%",
    }


# ── Trade context builder ────────────────────────────────────────────────────

async def get_trade_context(trade: dict) -> dict:
    """
    Build full market context for a trade record.
    Returns dict with all analysis; gracefully handles missing data.
    """
    code = trade.get("stock_code", "")
    trade_date = trade.get("trade_date", "")
    trade_price = float(trade.get("price", 0))
    direction = trade.get("direction", "buy")

    ctx: dict[str, Any] = {
        "code": code,
        "trade_date": trade_date,
        "offline": False,
        "error": None,
    }

    try:
        # Parallel fetch: stock info + kline + index
        context_start = (
            date.fromisoformat(trade_date) - timedelta(days=10)
        ).strftime("%Y-%m-%d")

        stock_info_task = asyncio.create_task(get_stock_info(code))
        kline_task = asyncio.create_task(get_daily_kline(code, context_start, trade_date))
        index_code = _index_for_code(code)
        index_task = asyncio.create_task(get_index_kline(index_code, trade_date))

        stock_info, kline_data, index_bar = await asyncio.gather(
            stock_info_task, kline_task, index_task,
            return_exceptions=True,
        )

        # Stock info
        if isinstance(stock_info, Exception):
            ctx["stock_info"] = {"code": code, "name": trade.get("stock_name") or code}
        else:
            ctx["stock_info"] = stock_info

        # Kline
        if isinstance(kline_data, Exception) or not kline_data:
            ctx["kline"] = []
            ctx["today_bar"] = None
            ctx["offline"] = True
        else:
            ctx["kline"] = kline_data
            # Find today's bar
            today_bars = [b for b in kline_data if b["date"] == trade_date]
            ctx["today_bar"] = today_bars[-1] if today_bars else kline_data[-1] if kline_data else None

        # Analysis (only if we have today's bar)
        today_bar = ctx.get("today_bar")
        if today_bar and trade_price > 0:
            vwap = _calc_vwap(today_bar)
            ctx["slippage"] = calc_slippage(trade_price, vwap, direction)
            ctx["timing"] = eval_timing(trade_price, today_bar, direction)
            ctx["today_change_pct"] = today_bar.get("change_pct", 0)
        else:
            ctx["slippage"] = None
            ctx["timing"] = None
            ctx["today_change_pct"] = None

        # Index comparison
        index_names = {"sh": "上证指数", "sz": "深证成指", "cyb": "创业板指"}
        if not isinstance(index_bar, Exception) and index_bar and ctx.get("today_change_pct") is not None:
            ctx["vs_index"] = compare_with_index(
                ctx["today_change_pct"],
                index_bar.get("change_pct", 0),
                index_names.get(index_code, "大盘"),
            )
            ctx["index_bar"] = index_bar
        else:
            ctx["vs_index"] = None
            ctx["index_bar"] = None

    except Exception as e:
        logger.warning(f"get_trade_context failed for {code}: {e}")
        ctx["error"] = str(e)
        ctx["offline"] = True

    return ctx


def format_context_for_ai(ctx: dict) -> str:
    """Format trade context into a compact string for AI prompts."""
    if ctx.get("offline") or not ctx.get("today_bar"):
        return ""

    parts = []
    info = ctx.get("stock_info", {})
    name = info.get("name", ctx.get("code", ""))
    parts.append(f"【{name}({ctx['code']}) {ctx['trade_date']}行情】")

    bar = ctx["today_bar"]
    parts.append(f"开{bar['open']:.2f} 高{bar['high']:.2f} 低{bar['low']:.2f} 收{bar['close']:.2f} 涨跌{bar.get('change_pct', 0):+.2f}%")

    if ctx.get("slippage"):
        s = ctx["slippage"]
        parts.append(f"滑点分析：{s['detail']}（{s['label']}）")

    if ctx.get("timing"):
        t = ctx["timing"]
        parts.append(f"时机评分：{t['score']}分/{t['label']} — {t['detail']}")

    if ctx.get("vs_index"):
        v = ctx["vs_index"]
        parts.append(f"大盘对比：{v['detail']}")

    return "\n".join(parts)
