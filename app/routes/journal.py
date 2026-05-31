"""Journal routes - daily trading journal/notes."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator
from datetime import date
from app.database import get_db

router = APIRouter(prefix="/api/journal", tags=["journal"])


class JournalEntry(BaseModel):
    content: str
    trade_date: str | None = None

    @field_validator("content")
    @classmethod
    def content_valid(cls, v):
        if not v.strip():
            raise ValueError("内容不能为空")
        if len(v) > 10000:
            raise ValueError("内容不能超过 10000 字符")
        return v.strip()


@router.get("")
async def get_journal(trade_date: str | None = None, limit: int = 10):
    db = await get_db()
    try:
        if trade_date:
            cursor = await db.execute(
                "SELECT * FROM journal WHERE trade_date = ? ORDER BY created_at DESC", (trade_date,)
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM journal ORDER BY trade_date DESC, created_at DESC LIMIT ?", (limit,)
            )
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


@router.post("")
async def create_journal(entry: JournalEntry):
    trade_date = entry.trade_date or date.today().isoformat()
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO journal (trade_date, content) VALUES (?, ?)",
            (trade_date, entry.content),
        )
        await db.commit()
        return {"id": cursor.lastrowid}
    finally:
        await db.close()


@router.delete("/{entry_id}")
async def delete_journal(entry_id: int):
    db = await get_db()
    try:
        cursor = await db.execute("DELETE FROM journal WHERE id = ?", (entry_id,))
        await db.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="记录不存在")
        return {"ok": True}
    finally:
        await db.close()
