"""Plans routes."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator
from datetime import date, timedelta
from app.database import get_db

router = APIRouter(prefix="/api/plans", tags=["plans"])


class PlanCreate(BaseModel):
    plan_type: str  # 'today' or 'tomorrow'
    content: str
    trade_date: str | None = None

    @field_validator("content")
    @classmethod
    def content_length(cls, v):
        if len(v) > 5000:
            raise ValueError("计划内容不能超过 5000 字符")
        if not v.strip():
            raise ValueError("计划内容不能为空")
        return v.strip()

    @field_validator("plan_type")
    @classmethod
    def valid_type(cls, v):
        if v not in ("today", "tomorrow"):
            raise ValueError("plan_type 必须为 today 或 tomorrow")
        return v


class PlanUpdate(BaseModel):
    content: str

    @field_validator("content")
    @classmethod
    def content_length(cls, v):
        if len(v) > 5000:
            raise ValueError("计划内容不能超过 5000 字符")
        if not v.strip():
            raise ValueError("计划内容不能为空")
        return v.strip()


@router.get("")
async def list_plans(trade_date: str | None = None, plan_type: str | None = None):
    if not trade_date:
        trade_date = date.today().isoformat()
    db = await get_db()
    try:
        query = "SELECT * FROM plans WHERE trade_date = ?"
        params: list = [trade_date]
        if plan_type:
            query += " AND plan_type = ?"
            params.append(plan_type)
        query += " ORDER BY created_at DESC"
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


@router.post("")
async def create_plan(plan: PlanCreate):
    trade_date = plan.trade_date or (
        date.today().isoformat() if plan.plan_type == "today"
        else (date.today() + timedelta(days=1)).isoformat()
    )
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO plans (plan_type, content, trade_date) VALUES (?, ?, ?)",
            (plan.plan_type, plan.content, trade_date),
        )
        await db.commit()
        return {"id": cursor.lastrowid, "trade_date": trade_date}
    finally:
        await db.close()


@router.put("/{plan_id}")
async def update_plan(plan_id: int, plan: PlanUpdate):
    db = await get_db()
    try:
        cursor = await db.execute(
            "UPDATE plans SET content = ? WHERE id = ?", (plan.content, plan_id)
        )
        await db.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="计划不存在")
        return {"ok": True}
    finally:
        await db.close()


@router.delete("/{plan_id}")
async def delete_plan(plan_id: int):
    db = await get_db()
    try:
        cursor = await db.execute("DELETE FROM plans WHERE id = ?", (plan_id,))
        await db.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="计划不存在")
        return {"ok": True}
    finally:
        await db.close()


@router.get("/warnings")
async def get_warnings():
    """Get high-weight vulnerabilities as warnings for plan page."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT tag, weight, description FROM vulnerability_matrix WHERE weight >= 2.0 ORDER BY weight DESC LIMIT 5"
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


@router.get("/templates")
async def list_templates():
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM plan_templates ORDER BY id DESC")
        return [dict(row) for row in await cursor.fetchall()]
    finally:
        await db.close()


@router.post("/templates")
async def create_template(plan: PlanUpdate):
    db = await get_db()
    try:
        cursor = await db.execute("INSERT INTO plan_templates (content) VALUES (?)", (plan.content,))
        await db.commit()
        return {"id": cursor.lastrowid}
    except Exception as e:
        if "UNIQUE" in str(e):
            raise HTTPException(status_code=409, detail="模板已存在")
        raise
    finally:
        await db.close()


@router.delete("/templates/{tpl_id}")
async def delete_template(tpl_id: int):
    db = await get_db()
    try:
        await db.execute("DELETE FROM plan_templates WHERE id = ?", (tpl_id,))
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()
