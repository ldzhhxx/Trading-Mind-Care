"""Vulnerability matrix routes."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator
from app.database import get_db

router = APIRouter(prefix="/api/vulnerabilities", tags=["vulnerabilities"])


class VulnCreate(BaseModel):
    tag: str
    weight: float = 1.0
    description: str = ""
    category: str = "未分类"

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
    category: str | None = None


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
            "INSERT INTO vulnerability_matrix (tag, weight, hit_count, last_hit_at, description, category) VALUES (?, ?, 0, ?, ?, ?)",
            (vuln.tag, vuln.weight, now, vuln.description, vuln.category),
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
        if vuln.category is not None:
            sets.append("category = ?")
            params.append(vuln.category)
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


@router.post("/analyze")
async def analyze_vulnerabilities():
    """AI analysis of vulnerability patterns - returns streaming response."""
    import json
    from fastapi.responses import StreamingResponse
    from app.llm import call_llm_stream

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT tag, weight, hit_count, last_hit_at, description FROM vulnerability_matrix ORDER BY weight DESC"
        )
        vulns = [dict(r) for r in await cursor.fetchall()]
        if not vulns:
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "暂无弱点数据"})
    finally:
        await db.close()

    vulns_text = "\n".join(
        f"- {v['tag']} (权重{v['weight']:.2f}, 触发{v['hit_count']}次, 最近{v['last_hit_at'] or '未知'})"
        for v in vulns
    )

    messages = [
        {"role": "system", "content": """你是一个交易心理分析师。分析交易员的弱点矩阵数据，找出：
1. 弱点之间的关联模式（哪些弱点经常一起出现）
2. 最危险的弱点组合
3. 改善建议的优先级排序
4. 一个具体的30天改善计划

简洁有力，200字以内。"""},
        {"role": "user", "content": f"弱点矩阵数据：\n{vulns_text}"},
    ]

    async def stream():
        try:
            async for chunk in call_llm_stream(messages):
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
