"""Trade records CRUD + natural language parsing."""
from __future__ import annotations
import json
import logging
from datetime import date
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from app.database import get_db
from app.market_data.parser import get_parser
from app.market_data.service import get_trade_context, get_stock_info

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/trades", tags=["trades"])


class TradeCreate(BaseModel):
    trade_date: str | None = None
    stock_code: str
    stock_name: str | None = None
    direction: str
    price: float
    quantity: int
    commission: float = 0.0
    note: str = ""
    review_id: int | None = None

    @field_validator("direction")
    @classmethod
    def dir_valid(cls, v: str) -> str:
        if v not in ("buy", "sell"):
            raise ValueError("direction must be buy or sell")
        return v

    @field_validator("price")
    @classmethod
    def price_valid(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("price must be positive")
        return v

    @field_validator("quantity")
    @classmethod
    def qty_valid(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("quantity must be positive")
        return v


class TradeUpdate(BaseModel):
    price: float | None = None
    quantity: int | None = None
    note: str | None = None
    review_id: int | None = None


class ParseRequest(BaseModel):
    text: str

    @field_validator("text")
    @classmethod
    def text_valid(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("text cannot be empty")
        return v


@router.post("/parse")
async def parse_trade(req: ParseRequest):
    """Parse natural language trade text into structured data."""
    parser = get_parser()

    # Try to load stock list for better name matching
    db = await get_db()
    try:
        cur = await db.execute("SELECT code, name FROM stock_list LIMIT 10000")
        rows = await cur.fetchall()
        if rows:
            parser.update_lookup([{"code": r["code"], "name": r["name"]} for r in rows])
    finally:
        await db.close()

    result = parser.parse(req.text)

    # Auto-fill stock name if we have code but no name
    if result["code"] and not result["name"]:
        db = await get_db()
        try:
            cur = await db.execute("SELECT name FROM stock_list WHERE code=?", (result["code"],))
            row = await cur.fetchone()
            if row:
                result["name"] = row["name"]
        finally:
            await db.close()

    return result


@router.post("")
async def create_trade(trade: TradeCreate):
    """Create a trade record."""
    trade_date = trade.trade_date or date.today().strftime("%Y-%m-%d")
    amount = round(trade.price * trade.quantity, 2)

    # Auto-fill stock name if missing
    stock_name = trade.stock_name
    if not stock_name:
        db = await get_db()
        try:
            cur = await db.execute("SELECT name FROM stock_list WHERE code=?", (trade.stock_code,))
            row = await cur.fetchone()
            stock_name = row["name"] if row else None
        finally:
            await db.close()

    db = await get_db()
    try:
        cur = await db.execute(
            """INSERT INTO trades (trade_date, stock_code, stock_name, direction, price, quantity,
               amount, commission, note, review_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (trade_date, trade.stock_code, stock_name, trade.direction,
             trade.price, trade.quantity, amount, trade.commission,
             trade.note, trade.review_id),
        )
        await db.commit()
        trade_id = cur.lastrowid
    finally:
        await db.close()

    return {"id": trade_id, "trade_date": trade_date, "amount": amount}


@router.get("")
async def list_trades(
    trade_date: str | None = None,
    stock_code: str | None = None,
    review_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """List trades with optional filters."""
    db = await get_db()
    try:
        conditions = []
        params: list = []
        if trade_date:
            conditions.append("trade_date = ?")
            params.append(trade_date)
        if stock_code:
            conditions.append("stock_code = ?")
            params.append(stock_code)
        if review_id is not None:
            conditions.append("review_id = ?")
            params.append(review_id)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params += [limit, offset]
        cur = await db.execute(
            f"SELECT * FROM trades {where} ORDER BY trade_date DESC, created_at DESC LIMIT ? OFFSET ?",
            params,
        )
        rows = [dict(r) for r in await cur.fetchall()]
        cur2 = await db.execute(f"SELECT COUNT(*) as cnt FROM trades {where}", params[:-2])
        total = (await cur2.fetchone())["cnt"]
    finally:
        await db.close()

    return {"items": rows, "total": total}


@router.get("/{trade_id}")
async def get_trade(trade_id: int):
    """Get a single trade record."""
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM trades WHERE id=?", (trade_id,))
        row = await cur.fetchone()
    finally:
        await db.close()
    if not row:
        raise HTTPException(404, "交易记录不存在")
    return dict(row)


@router.put("/{trade_id}")
async def update_trade(trade_id: int, update: TradeUpdate):
    """Update a trade record."""
    db = await get_db()
    try:
        cur = await db.execute("SELECT id FROM trades WHERE id=?", (trade_id,))
        if not await cur.fetchone():
            raise HTTPException(404, "交易记录不存在")

        fields, params = [], []
        if update.price is not None:
            fields.append("price=?")
            params.append(update.price)
        if update.quantity is not None:
            fields.append("quantity=?")
            params.append(update.quantity)
        if update.note is not None:
            fields.append("note=?")
            params.append(update.note)
        if update.review_id is not None:
            fields.append("review_id=?")
            params.append(update.review_id)

        if fields:
            # Recalculate amount if price/qty changed
            if update.price is not None or update.quantity is not None:
                cur2 = await db.execute("SELECT price, quantity FROM trades WHERE id=?", (trade_id,))
                existing = dict(await cur2.fetchone())
                p = update.price if update.price is not None else existing["price"]
                q = update.quantity if update.quantity is not None else existing["quantity"]
                fields.append("amount=?")
                params.append(round(p * q, 2))

            params.append(trade_id)
            await db.execute(f"UPDATE trades SET {', '.join(fields)} WHERE id=?", params)
            await db.commit()
    finally:
        await db.close()
    return {"ok": True}


@router.delete("/{trade_id}")
async def delete_trade(trade_id: int):
    """Delete a trade record."""
    db = await get_db()
    try:
        await db.execute("DELETE FROM trades WHERE id=?", (trade_id,))
        await db.commit()
    finally:
        await db.close()
    return {"ok": True}


@router.get("/{trade_id}/context")
async def trade_context(trade_id: int):
    """Get full market context for a trade."""
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM trades WHERE id=?", (trade_id,))
        row = await cur.fetchone()
    finally:
        await db.close()
    if not row:
        raise HTTPException(404, "交易记录不存在")

    ctx = await get_trade_context(dict(row))
    return ctx
