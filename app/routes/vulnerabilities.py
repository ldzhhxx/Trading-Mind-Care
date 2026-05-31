"""Vulnerability matrix routes."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator
from app.database import get_db

router = APIRouter(prefix="/api/vulnerabilities", tags=["vulnerabilities"])


class VulnCreate(BaseModel):
    tag: str
    weight: float = 1.0
    description: str = ""

    @field_validator("tag")
    @classmethod
    def tag_valid(cls, v):
        if not v.strip():
            raise ValueError("标签不能为空")
        return v.strip()


class VulnUpdate(BaseModel):
    tag: str | None = None
    weight: float | None = None
    description: str | None = None


@router.get("")
async def list_vulnerabilities():
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM vulnerability_matrix ORDER BY weight DESC"
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


@router.post("")
async def create_vulnerability(vuln: VulnCreate):
    db = await get_db()
    try:
        from datetime import date
        now = date.today().isoformat()
        cursor = await db.execute(
            "INSERT INTO vulnerability_matrix (tag, weight, hit_count, last_hit_at, description) VALUES (?, ?, 0, ?, ?)",
            (vuln.tag, vuln.weight, now, vuln.description),
        )
        await db.commit()
        return {"id": cursor.lastrowid}
    except Exception as e:
        if "UNIQUE" in str(e):
            raise HTTPException(status_code=409, detail="该弱点标签已存在")
        raise
    finally:
        await db.close()


@router.put("/{vuln_id}")
async def update_vulnerability(vuln_id: int, vuln: VulnUpdate):
    db = await get_db()
    try:
        sets, params = [], []
        if vuln.tag is not None:
            sets.append("tag = ?")
            params.append(vuln.tag.strip())
        if vuln.weight is not None:
            sets.append("weight = ?")
            params.append(vuln.weight)
        if vuln.description is not None:
            sets.append("description = ?")
            params.append(vuln.description)
        if not sets:
            return {"ok": True}
        params.append(vuln_id)
        cursor = await db.execute(f"UPDATE vulnerability_matrix SET {', '.join(sets)} WHERE id = ?", params)
        await db.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="弱点不存在")
        return {"ok": True}
    finally:
        await db.close()


@router.delete("/{vuln_id}")
async def delete_vulnerability(vuln_id: int):
    db = await get_db()
    try:
        await db.execute("DELETE FROM vulnerability_matrix WHERE id = ?", (vuln_id,))
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


@router.post("/merge")
async def merge_vulnerabilities(source_id: int, target_id: int):
    """Merge source vulnerability into target (combine weights and hit counts)."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM vulnerability_matrix WHERE id = ?", (source_id,))
        source = await cursor.fetchone()
        cursor = await db.execute("SELECT * FROM vulnerability_matrix WHERE id = ?", (target_id,))
        target = await cursor.fetchone()
        if not source or not target:
            raise HTTPException(status_code=404, detail="弱点不存在")

        new_weight = target["weight"] + source["weight"] * 0.5
        new_hits = target["hit_count"] + source["hit_count"]
        await db.execute(
            "UPDATE vulnerability_matrix SET weight = ?, hit_count = ? WHERE id = ?",
            (new_weight, new_hits, target_id),
        )
        await db.execute("DELETE FROM vulnerability_matrix WHERE id = ?", (source_id,))
        await db.commit()
        return {"ok": True, "new_weight": new_weight, "new_hits": new_hits}
    finally:
        await db.close()


@router.post("/{vuln_id}/reset")
async def reset_vulnerability(vuln_id: int):
    """Reset a vulnerability's weight to 1.0 (fresh start)."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "UPDATE vulnerability_matrix SET weight = 1.0 WHERE id = ?", (vuln_id,)
        )
        await db.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="弱点不存在")
        return {"ok": True}
    finally:
        await db.close()
