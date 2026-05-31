"""Trade rules routes - personal trading discipline rules."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator
from app.database import get_db

router = APIRouter(prefix="/api/rules", tags=["rules"])


class RuleCreate(BaseModel):
    rule: str
    category: str = "general"

    @field_validator("rule")
    @classmethod
    def rule_valid(cls, v):
        if not v.strip():
            raise ValueError("规则不能为空")
        return v.strip()


@router.get("")
async def list_rules(active_only: bool = True):
    db = await get_db()
    try:
        if active_only:
            cursor = await db.execute("SELECT * FROM trade_rules WHERE active = 1 ORDER BY category, id")
        else:
            cursor = await db.execute("SELECT * FROM trade_rules ORDER BY category, id")
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


@router.post("")
async def create_rule(rule: RuleCreate):
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO trade_rules (rule, category) VALUES (?, ?)",
            (rule.rule, rule.category),
        )
        await db.commit()
        return {"id": cursor.lastrowid}
    finally:
        await db.close()


@router.patch("/{rule_id}/toggle")
async def toggle_rule(rule_id: int):
    db = await get_db()
    try:
        await db.execute("UPDATE trade_rules SET active = 1 - active WHERE id = ?", (rule_id,))
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


@router.delete("/{rule_id}")
async def delete_rule(rule_id: int):
    db = await get_db()
    try:
        cursor = await db.execute("DELETE FROM trade_rules WHERE id = ?", (rule_id,))
        await db.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="规则不存在")
        return {"ok": True}
    finally:
        await db.close()
