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
    category: str = "通用"

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
            "INSERT INTO plans (plan_type, content, trade_date, category) VALUES (?, ?, ?, ?)",
            (plan.plan_type, plan.content, trade_date, plan.category),
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


@router.patch("/{plan_id}/toggle")
async def toggle_plan_done(plan_id: int):
    db = await get_db()
    try:
        await db.execute("UPDATE plans SET done = 1 - done WHERE id = ?", (plan_id,))
        await db.commit()
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
async def get_warnings(content: str | None = None):
    """Get high-weight vulnerabilities as warnings. If content provided, also match keywords."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, tag, weight, description FROM vulnerability_matrix WHERE weight >= 2.0 ORDER BY weight DESC LIMIT 5"
        )
        rows = [dict(row) for row in await cursor.fetchall()]

        # If content provided, also check keyword matches from ALL vulnerabilities
        if content:
            cursor = await db.execute(
                "SELECT id, tag, weight, description FROM vulnerability_matrix ORDER BY weight DESC"
            )
            all_vulns = [dict(r) for r in await cursor.fetchall()]
            existing_ids = {r["id"] for r in rows}
            for v in all_vulns:
                if v["id"] in existing_ids:
                    continue
                # Simple keyword match: if any word in the tag appears in content
                tag_words = [w for w in v["tag"] if len(w) >= 2]
                if v["tag"] in content or any(w in content for w in v["tag"].split()):
                    v["matched"] = True
                    rows.append(v)

        return rows
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


@router.post("/copy-yesterday")
async def copy_yesterday_plans():
    """Copy yesterday's today-plans to today."""
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    today_str = date.today().isoformat()
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT content FROM plans WHERE trade_date = ? AND plan_type = 'today'", (yesterday,)
        )
        rows = await cursor.fetchall()
        if not rows:
            raise HTTPException(status_code=404, detail="昨日无计划可复制")
        copied = 0
        for row in rows:
            await db.execute(
                "INSERT INTO plans (plan_type, content, trade_date) VALUES ('today', ?, ?)",
                (row["content"], today_str),
            )
            copied += 1
        await db.commit()
        return {"copied": copied}
    finally:
        await db.close()


@router.post("/batch-complete")
async def batch_complete_plans(trade_date: str | None = None):
    """Mark all today's plans as done."""
    trade_date = trade_date or date.today().isoformat()
    db = await get_db()
    try:
        cursor = await db.execute(
            "UPDATE plans SET done = 1 WHERE trade_date = ? AND plan_type = 'today' AND done = 0",
            (trade_date,),
        )
        await db.commit()
        return {"completed": cursor.rowcount}
    finally:
        await db.close()


@router.post("/batch-reset")
async def batch_reset_plans(trade_date: str | None = None):
    """Reset all today's plans to undone."""
    trade_date = trade_date or date.today().isoformat()
    db = await get_db()
    try:
        cursor = await db.execute(
            "UPDATE plans SET done = 0 WHERE trade_date = ? AND plan_type = 'today' AND done = 1",
            (trade_date,),
        )
        await db.commit()
        return {"reset": cursor.rowcount}
    finally:
        await db.close()


@router.get("/execution-trend")
async def plan_execution_trend():
    """计划完成率趋势图数据（近30天）."""
    today = date.today()
    db = await get_db()
    try:
        results = []
        for i in range(29, -1, -1):
            d = (today - timedelta(days=i)).isoformat()
            cursor = await db.execute(
                "SELECT COUNT(*) as total, SUM(done) as completed FROM plans WHERE trade_date = ? AND plan_type='today'",
                (d,)
            )
            row = await cursor.fetchone()
            total = row["total"]
            completed = row["completed"] or 0
            if total > 0:
                results.append({"date": d, "rate": round(completed / total * 100, 1), "total": total, "completed": completed})
        return results
    finally:
        await db.close()
