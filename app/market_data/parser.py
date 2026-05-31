"""Trade text parser and stock code resolver."""
from __future__ import annotations
import re
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── Regex patterns ──────────────────────────────────────────────────────────
_CODE_RE = re.compile(r'\b([036]\d{5})\b')
_QTY_RE = re.compile(r'(\d+)\s*[股手张]')
_PRICE_RE = re.compile(r'[@＠]\s*([\d.]+)|(\d+\.?\d*)\s*元|价格?\s*([\d.]+)')
_BUY_KW = re.compile(r'买[入了]?|建仓|加仓|开多|做多|long')
_SELL_KW = re.compile(r'卖[出了]?|平仓|减仓|清仓|止损|止盈|做空|short')

# Common stock name aliases → code
_NAME_ALIASES: dict[str, str] = {
    "茅台": "600519", "贵州茅台": "600519",
    "平安": "601318", "中国平安": "601318",
    "工行": "601398", "工商银行": "601398",
    "建行": "601939", "建设银行": "601939",
    "招行": "600036", "招商银行": "600036",
    "宁德": "300750", "宁德时代": "300750",
    "比亚迪": "002594",
    "腾讯": "00700",  # HK
    "平安银行": "000001",
    "万科": "000002",
    "格力": "000651", "格力电器": "000651",
    "美的": "000333", "美的集团": "000333",
    "中芯": "688981", "中芯国际": "688981",
    "隆基": "601012", "隆基绿能": "601012",
    "东方财富": "300059",
    "海天味业": "603288",
    "五粮液": "000858",
    "泸州老窖": "000568",
    "恒瑞医药": "600276",
    "迈瑞医疗": "300760",
    "药明康德": "603259",
    "中国移动": "600941",
    "中国联通": "600050",
    "中国电信": "601728",
}


class TradeParser:
    """Parse natural-language trade text into structured data."""

    def __init__(self, stock_lookup: dict[str, str] | None = None) -> None:
        # stock_lookup: name → code, merged with aliases
        self._lookup: dict[str, str] = dict(_NAME_ALIASES)
        if stock_lookup:
            self._lookup.update(stock_lookup)

    def parse(self, text: str) -> dict[str, Any]:
        """
        Parse trade text. Returns dict with keys:
          code, name, direction, quantity, price, raw, errors
        Missing fields are None; errors is a list of strings.
        """
        result: dict[str, Any] = {
            "code": None, "name": None,
            "direction": None, "quantity": None, "price": None,
            "raw": text, "errors": [],
        }

        # 1. Stock code (6-digit)
        m = _CODE_RE.search(text)
        if m:
            result["code"] = m.group(1)
        else:
            # Try name lookup
            for name, code in self._lookup.items():
                if name in text:
                    result["code"] = code
                    result["name"] = name
                    break

        # 2. Direction
        if _BUY_KW.search(text):
            result["direction"] = "buy"
        elif _SELL_KW.search(text):
            result["direction"] = "sell"
        else:
            result["errors"].append("无法识别买卖方向")

        # 3. Quantity
        m = _QTY_RE.search(text)
        if m:
            result["quantity"] = int(m.group(1))

        # 4. Price — try @price, then X元, then bare number after direction keyword
        pm = _PRICE_RE.search(text)
        if pm:
            val = pm.group(1) or pm.group(2) or pm.group(3)
            if val:
                result["price"] = float(val)
        else:
            # Last resort: find a decimal number that looks like a price
            nums = re.findall(r'\b(\d{1,6}\.?\d{0,4})\b', text)
            # Filter out the stock code and quantity
            candidates = [
                float(n) for n in nums
                if n != result["code"]
                and (result["quantity"] is None or int(float(n)) != result["quantity"])
                and float(n) > 0.1
            ]
            if candidates:
                result["price"] = candidates[-1]

        if not result["code"]:
            result["errors"].append("无法识别股票代码，请输入6位代码或股票名称")

        return result

    def update_lookup(self, stock_list: list[dict]) -> None:
        """Update name→code lookup from stock list."""
        for item in stock_list:
            code = item.get("code", "")
            name = item.get("name", "")
            if code and name:
                self._lookup[name] = code
                # Also add short name (strip spaces)
                short = name.replace(" ", "").replace("\u3000", "")
                if short != name:
                    self._lookup[short] = code

    def search(self, query: str, stock_list: list[dict], limit: int = 10) -> list[dict]:
        """Fuzzy search stocks by code or name prefix."""
        q = query.strip().upper()
        results = []
        for item in stock_list:
            code = item.get("code", "")
            name = item.get("name", "").replace(" ", "")
            if code.startswith(q) or name.startswith(query) or q in name.upper():
                results.append({"code": code, "name": name})
                if len(results) >= limit:
                    break
        return results


# Module-level singleton
_parser: TradeParser | None = None


def get_parser() -> TradeParser:
    global _parser
    if _parser is None:
        _parser = TradeParser()
    return _parser
