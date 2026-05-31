"""Data export/import routes."""
import csv
import io
import json
import shutil
from fastapi import APIRouter, UploadFile, File
from fastapi.responses import StreamingResponse, FileResponse
from app.database import get_db, get_db_path

router = APIRouter(prefix="/api/data", tags=["data"])


@router.get("/export/reviews")
async def export_reviews(format: str = "json"):
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM reviews ORDER BY trade_date DESC")
        rows = [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()

    if format == "csv":
        output = io.StringIO()
        if rows:
            writer = csv.DictWriter(output, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=reviews.csv"},
        )
    return rows


@router.get("/export/vulnerabilities")
async def export_vulnerabilities(format: str = "json"):
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM vulnerability_matrix ORDER BY weight DESC")
        rows = [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()

    if format == "csv":
        output = io.StringIO()
        if rows:
            writer = csv.DictWriter(output, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=vulnerabilities.csv"},
        )
    return rows


@router.get("/backup")
async def backup_database():
    """Download the SQLite database file."""
    db_path = get_db_path()
    return FileResponse(db_path, filename="mind_care_backup.db", media_type="application/octet-stream")


@router.post("/import/reviews")
async def import_reviews(file: UploadFile = File(...)):
    """Import reviews from JSON file."""
    content = await file.read()
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return {"error": "无效的 JSON 文件", "imported": 0}

    if not isinstance(data, list):
        return {"error": "JSON 必须是数组格式", "imported": 0}

    db = await get_db()
    imported = 0
    try:
        for r in data:
            trade_date = r.get("trade_date")
            emotion_log = r.get("emotion_log")
            if not trade_date or not emotion_log:
                continue
            await db.execute(
                "INSERT INTO reviews (trade_date, pnl, emotion_log, ai_critique) VALUES (?, ?, ?, ?)",
                (trade_date, r.get("pnl"), emotion_log, r.get("ai_critique")),
            )
            imported += 1
        await db.commit()
    finally:
        await db.close()
    return {"imported": imported}
