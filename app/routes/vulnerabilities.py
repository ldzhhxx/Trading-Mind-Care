"""Vulnerability matrix routes."""
from fastapi import APIRouter
from app.database import get_db

router = APIRouter(prefix="/api/vulnerabilities", tags=["vulnerabilities"])


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


@router.delete("/{vuln_id}")
async def delete_vulnerability(vuln_id: int):
    db = await get_db()
    try:
        await db.execute("DELETE FROM vulnerability_matrix WHERE id = ?", (vuln_id,))
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()
