"""Market data provider abstraction layer."""
from __future__ import annotations
import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import date, timedelta
from typing import Any

logger = logging.getLogger(__name__)


class MarketDataProvider(ABC):
    """Abstract base for market data sources."""

    @abstractmethod
    async def get_daily_kline(self, code: str, start_date: str, end_date: str) -> list[dict]:
        """Return daily OHLCV bars. Dates: YYYY-MM-DD."""

    @abstractmethod
    async def get_stock_info(self, code: str) -> dict:
        """Return {code, name, industry, market}."""

    @abstractmethod
    async def get_index_kline(self, index_code: str, trade_date: str) -> dict | None:
        """Return single-day bar for an index (sh/sz/cyb)."""

    @abstractmethod
    async def get_stock_list(self) -> list[dict]:
        """Return [{code, name}, ...] for all A-share stocks."""


class AkShareProvider(MarketDataProvider):
    """akshare data source — primary."""

    async def get_daily_kline(self, code: str, start_date: str, end_date: str) -> list[dict]:
        import akshare as ak
        loop = asyncio.get_event_loop()
        start = start_date.replace("-", "")
        end = end_date.replace("-", "")
        df = await loop.run_in_executor(
            None,
            lambda: ak.stock_zh_a_hist(symbol=code, period="daily", start_date=start, end_date=end, adjust="")
        )
        result = []
        for _, row in df.iterrows():
            result.append({
                "date": str(row.get("日期", row.get("date", "")))[:10],
                "open": float(row.get("开盘", row.get("open", 0))),
                "high": float(row.get("最高", row.get("high", 0))),
                "low": float(row.get("最低", row.get("low", 0))),
                "close": float(row.get("收盘", row.get("close", 0))),
                "volume": float(row.get("成交量", row.get("volume", 0))),
                "amount": float(row.get("成交额", row.get("amount", 0))),
                "change_pct": float(row.get("涨跌幅", row.get("change_pct", 0))),
            })
        return result

    async def get_stock_info(self, code: str) -> dict:
        import akshare as ak
        loop = asyncio.get_event_loop()
        df = await loop.run_in_executor(None, lambda: ak.stock_individual_info_em(symbol=code))
        info: dict[str, Any] = {"code": code}
        for _, row in df.iterrows():
            key = str(row.iloc[0])
            val = str(row.iloc[1])
            if "股票简称" in key or "名称" in key:
                info["name"] = val
            elif "行业" in key:
                info["industry"] = val
            elif "总市值" in key:
                info["market_cap"] = val
        return info

    async def get_index_kline(self, index_code: str, trade_date: str) -> dict | None:
        import akshare as ak
        loop = asyncio.get_event_loop()
        # index_code: sh=上证 sz=深证 cyb=创业板
        symbol_map = {"sh": "000001", "sz": "399001", "cyb": "399006"}
        symbol = symbol_map.get(index_code, index_code)
        start = trade_date.replace("-", "")
        df = await loop.run_in_executor(
            None,
            lambda: ak.stock_zh_index_daily(symbol=f"sh{symbol}" if index_code == "sh" else f"sz{symbol}")
        )
        if df is None or df.empty:
            return None
        df["date_str"] = df["date"].astype(str).str[:10]
        row = df[df["date_str"] == trade_date]
        if row.empty:
            return None
        r = row.iloc[0]
        return {
            "date": trade_date,
            "open": float(r.get("open", 0)),
            "high": float(r.get("high", 0)),
            "low": float(r.get("low", 0)),
            "close": float(r.get("close", 0)),
            "change_pct": float(r.get("change_pct", 0)) if "change_pct" in r else 0.0,
        }

    async def get_stock_list(self) -> list[dict]:
        import akshare as ak
        loop = asyncio.get_event_loop()
        df = await loop.run_in_executor(None, ak.stock_info_a_code_name)
        return [{"code": str(row["code"]), "name": str(row["name"])} for _, row in df.iterrows()]


class SinaProvider(MarketDataProvider):
    """Sina Finance fallback — uses public HTTP API, no registration needed."""

    async def get_daily_kline(self, code: str, start_date: str, end_date: str) -> list[dict]:
        import httpx
        # Sina historical data API
        prefix = "sh" if code.startswith("6") else "sz"
        url = f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
        params = {
            "symbol": f"{prefix}{code}",
            "type": "D",
            "datalen": 60,
        }
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
        import json, re
        text = resp.text.strip()
        # Response is JS-like: [{day:"...", open:"...", ...}]
        text = re.sub(r'(\w+):', r'"\1":', text)
        data = json.loads(text)
        result = []
        for item in data:
            d = item.get("day", "")[:10]
            if d < start_date or d > end_date:
                continue
            prev_close = float(item.get("close", 0))
            close = float(item.get("close", 0))
            result.append({
                "date": d,
                "open": float(item.get("open", 0)),
                "high": float(item.get("high", 0)),
                "low": float(item.get("low", 0)),
                "close": close,
                "volume": float(item.get("volume", 0)),
                "amount": 0.0,
                "change_pct": 0.0,
            })
        return result

    async def get_stock_info(self, code: str) -> dict:
        import httpx
        prefix = "sh" if code.startswith("6") else "sz"
        url = f"https://hq.sinajs.cn/list={prefix}{code}"
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, headers={"Referer": "https://finance.sina.com.cn"})
        text = resp.text
        # var hq_str_sh600519="贵州茅台,1800.00,..."
        import re
        m = re.search(r'"([^"]+)"', text)
        if not m:
            return {"code": code, "name": code}
        parts = m.group(1).split(",")
        return {"code": code, "name": parts[0] if parts else code}

    async def get_index_kline(self, index_code: str, trade_date: str) -> dict | None:
        return None  # Sina index API is complex; skip for fallback

    async def get_stock_list(self) -> list[dict]:
        return []  # Not supported in fallback


class MarketDataManager:
    """Manages providers with automatic fallback."""

    def __init__(self) -> None:
        self._providers: list[MarketDataProvider] = []
        self._init_providers()

    def _init_providers(self) -> None:
        try:
            import akshare  # noqa: F401
            self._providers.append(AkShareProvider())
        except ImportError:
            logger.warning("akshare not installed, skipping primary provider")
        self._providers.append(SinaProvider())

    async def _try_all(self, method: str, *args, **kwargs) -> Any:
        last_err: Exception | None = None
        for provider in self._providers:
            try:
                return await asyncio.wait_for(
                    getattr(provider, method)(*args, **kwargs),
                    timeout=10.0
                )
            except Exception as e:
                last_err = e
                logger.warning(f"{provider.__class__.__name__}.{method} failed: {e}")
        raise Exception(f"所有数据源均不可用: {last_err}")

    async def get_daily_kline(self, code: str, start_date: str, end_date: str) -> list[dict]:
        return await self._try_all("get_daily_kline", code, start_date, end_date)

    async def get_stock_info(self, code: str) -> dict:
        return await self._try_all("get_stock_info", code)

    async def get_index_kline(self, index_code: str, trade_date: str) -> dict | None:
        return await self._try_all("get_index_kline", index_code, trade_date)

    async def get_stock_list(self) -> list[dict]:
        return await self._try_all("get_stock_list")


# Singleton
_manager: MarketDataManager | None = None


def get_market_manager() -> MarketDataManager:
    global _manager
    if _manager is None:
        _manager = MarketDataManager()
    return _manager
