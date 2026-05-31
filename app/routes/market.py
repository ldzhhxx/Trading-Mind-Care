"""Market data API routes."""
from __future__ import annotations
import logging
from fastapi import APIRouter, HTTPException, Query

from app.market_data.service import (
    get_daily_kline, get_stock_info, get_index_kline,
    get_stock_list_cached, calc_slippage, eval_timing,
)
from app.market_data.parser import get_parser
from app.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/market", tags=["market"])


@router.get("/search")
async def search_stocks(q: str = Query(..., min_length=1)):
    """Search stocks by code or name."""
    # First try local DB (fast)
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT code, name FROM stock_list WHERE code LIKE ? OR name LIKE ? LIMIT 15",
            (f"{q}%", f"%{q}%"),
        )
        rows = [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()

    if rows:
        return {"items": rows}

    # Fallback: try to fetch from network
    try:
        stocks = await get_stock_list_cached()
        parser = get_parser()
        results = parser.search(q, stocks)
        return {"items": results}
    except Exception as e:
        logger.warning(f"Stock search failed: {e}")
        return {"items": []}


@router.get("/stock-info/{code}")
async def stock_info(code: str):
    """Get stock basic info."""
    try:
        info = await get_stock_info(code)
        return info
    except Exception as e:
        raise HTTPException(503, f"获取股票信息失败: {e}")


@router.get("/kline/{code}")
async def kline(code: str, start: str = Query(...), end: str = Query(...)):
    """Get daily kline data."""
    try:
        bars = await get_daily_kline(code, start, end)
        return {"code": code, "bars": bars}
    except Exception as e:
        raise HTTPException(503, f"获取K线数据失败: {e}")


@router.get("/index/{index_code}")
async def index_quote(index_code: str, trade_date: str = Query(...)):
    """Get index quote for a specific date."""
    try:
        bar = await get_index_kline(index_code, trade_date)
        if not bar:
            raise HTTPException(404, "未找到指数数据")
        return bar
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(503, f"获取指数数据失败: {e}")


@router.post("/refresh-stock-list")
async def refresh_stock_list():
    """Refresh the local stock list from network."""
    try:
        stocks = await get_stock_list_cached()
        return {"count": len(stocks), "ok": True}
    except Exception as e:
        raise HTTPException(503, f"刷新股票列表失败: {e}")


@router.get("/daily-summary")
async def daily_summary(trade_date: str = Query(...)):
    """Get summary of all trades on a given date with market context."""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM trades WHERE trade_date=? ORDER BY created_at",
            (trade_date,),
        )
        trades = [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()

    if not trades:
        return {"trade_date": trade_date, "trades": [], "summary": None}

    # Aggregate stats
    total_buy = sum(t["amount"] or 0 for t in trades if t["direction"] == "buy")
    total_sell = sum(t["amount"] or 0 for t in trades if t["direction"] == "sell")
    codes = list({t["stock_code"] for t in trades})

    return {
        "trade_date": trade_date,
        "trades": trades,
        "summary": {
            "trade_count": len(trades),
            "stock_count": len(codes),
            "total_buy": round(total_buy, 2),
            "total_sell": round(total_sell, 2),
            "codes": codes,
        },
    }
