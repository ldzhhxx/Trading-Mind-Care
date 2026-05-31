"""Data export/import routes."""
import csv
import io
import json
import os
import shutil
import logging
from fastapi import APIRouter, UploadFile, File
from fastapi.responses import StreamingResponse, FileResponse
from app.database import get_db, get_db_path

router = APIRouter(prefix="/api/data", tags=["data"])
logger = logging.getLogger(__name__)


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


@router.get("/health")
async def data_health_check():
    """Check database integrity and return health report."""
    db = await get_db()
    try:
        # Integrity check
        cursor = await db.execute("PRAGMA integrity_check")
        integrity = (await cursor.fetchone())[0]

        # DB size
        cursor = await db.execute("SELECT page_count * page_size as size FROM pragma_page_count(), pragma_page_size()")
        row = await cursor.fetchone()
        db_size = row[0] if row else 0

        # Record counts
        cursor = await db.execute("SELECT COUNT(*) as c FROM reviews")
        review_count = (await cursor.fetchone())["c"]
        cursor = await db.execute("SELECT COUNT(*) as c FROM plans")
        plan_count = (await cursor.fetchone())["c"]
        cursor = await db.execute("SELECT COUNT(*) as c FROM vulnerability_matrix")
        vuln_count = (await cursor.fetchone())["c"]

        # Orphan detection: reviews with impossible dates
        cursor = await db.execute("SELECT COUNT(*) as c FROM reviews WHERE trade_date > date('now', '+1 day')")
        future_reviews = (await cursor.fetchone())["c"]

        # Duplicate detection
        cursor = await db.execute(
            "SELECT trade_date, emotion_log, COUNT(*) as c FROM reviews GROUP BY trade_date, emotion_log HAVING c > 1"
        )
        duplicates = len(await cursor.fetchall())

        return {
            "integrity": integrity,
            "db_size_kb": round(db_size / 1024, 1),
            "review_count": review_count,
            "plan_count": plan_count,
            "vuln_count": vuln_count,
            "issues": {
                "future_reviews": future_reviews,
                "duplicate_reviews": duplicates,
            },
            "healthy": integrity == "ok" and future_reviews == 0,
        }
    finally:
        await db.close()


@router.get("/export/all")
async def export_all():
    """Export all data as a single JSON for complete backup."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM reviews ORDER BY trade_date DESC")
        reviews = [dict(r) for r in await cursor.fetchall()]
        cursor = await db.execute("SELECT * FROM plans ORDER BY trade_date DESC")
        plans = [dict(r) for r in await cursor.fetchall()]
        cursor = await db.execute("SELECT * FROM vulnerability_matrix ORDER BY weight DESC")
        vulns = [dict(r) for r in await cursor.fetchall()]
        cursor = await db.execute("SELECT * FROM plan_templates")
        templates = [dict(r) for r in await cursor.fetchall()]
        cursor = await db.execute("SELECT * FROM trade_rules")
        rules = [dict(r) for r in await cursor.fetchall()]
        cursor = await db.execute("SELECT * FROM journal ORDER BY trade_date DESC")
        journal = [dict(r) for r in await cursor.fetchall()]
        cursor = await db.execute("SELECT key, value FROM sys_config WHERE key NOT IN ('api_key')")
        config = {r["key"]: r["value"] for r in await cursor.fetchall()}
    finally:
        await db.close()

    from datetime import date as d
    export = {
        "export_date": d.today().isoformat(),
        "version": "3.0",
        "reviews": reviews,
        "plans": plans,
        "vulnerability_matrix": vulns,
        "plan_templates": templates,
        "trade_rules": rules,
        "journal": journal,
        "config": config,
    }

    output = io.StringIO()
    output.write(json.dumps(export, ensure_ascii=False, indent=2))
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=trading_mind_care_full_backup.json"},
    )


@router.post("/auto-backup")
async def auto_backup():
    """Create an automatic timestamped backup of the database."""
    from datetime import datetime
    db_path = get_db_path()
    backup_dir = os.path.join(os.path.dirname(db_path), "backups")
    os.makedirs(backup_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(backup_dir, f"mind_care_{timestamp}.db")

    # Limit to 7 backups
    existing = sorted(
        [f for f in os.listdir(backup_dir) if f.endswith(".db")],
        reverse=True
    )
    for old in existing[6:]:
        try:
            os.remove(os.path.join(backup_dir, old))
        except Exception:
            pass

    try:
        shutil.copy2(db_path, backup_path)
        size_kb = round(os.path.getsize(backup_path) / 1024, 1)
        return {"ok": True, "path": backup_path, "size_kb": size_kb, "timestamp": timestamp}
    except Exception as e:
        logger.error(f"Auto-backup failed: {e}")
        return {"ok": False, "error": str(e)}


@router.get("/backups")
async def list_backups():
    """List available database backups."""
    db_path = get_db_path()
    backup_dir = os.path.join(os.path.dirname(db_path), "backups")
    if not os.path.exists(backup_dir):
        return []
    files = sorted(
        [f for f in os.listdir(backup_dir) if f.endswith(".db")],
        reverse=True
    )
    return [
        {"name": f, "size_kb": round(os.path.getsize(os.path.join(backup_dir, f)) / 1024, 1)}
        for f in files
    ]


@router.post("/import/all")
async def import_all(file: UploadFile = File(...)):
    """Import full backup JSON (exported from /api/data/export/all)."""
    content = await file.read()
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return {"error": "无效的 JSON 文件", "imported": {}}

    if not isinstance(data, dict):
        return {"error": "JSON 格式不正确", "imported": {}}

    db = await get_db()
    counts = {}
    try:
        # Import reviews
        for r in data.get("reviews", []):
            if not r.get("trade_date") or not r.get("emotion_log"):
                continue
            await db.execute(
                "INSERT OR IGNORE INTO reviews (trade_date, pnl, emotion_log, ai_critique, mood) VALUES (?, ?, ?, ?, ?)",
                (r["trade_date"], r.get("pnl"), r["emotion_log"], r.get("ai_critique"), r.get("mood")),
            )
        counts["reviews"] = len(data.get("reviews", []))

        # Import plans
        for p in data.get("plans", []):
            if not p.get("content") or not p.get("trade_date"):
                continue
            await db.execute(
                "INSERT OR IGNORE INTO plans (plan_type, content, trade_date, done) VALUES (?, ?, ?, ?)",
                (p.get("plan_type", "today"), p["content"], p["trade_date"], p.get("done", 0)),
            )
        counts["plans"] = len(data.get("plans", []))

        # Import vulnerability matrix
        for v in data.get("vulnerability_matrix", []):
            if not v.get("tag"):
                continue
            await db.execute(
                "INSERT OR IGNORE INTO vulnerability_matrix (tag, weight, hit_count, last_hit_at, description, category) VALUES (?, ?, ?, ?, ?, ?)",
                (v["tag"], v.get("weight", 1.0), v.get("hit_count", 0), v.get("last_hit_at"), v.get("description"), v.get("category", "未分类")),
            )
        counts["vulnerabilities"] = len(data.get("vulnerability_matrix", []))

        # Import trade rules
        for r in data.get("trade_rules", []):
            if not r.get("rule"):
                continue
            await db.execute(
                "INSERT OR IGNORE INTO trade_rules (rule, category, active) VALUES (?, ?, ?)",
                (r["rule"], r.get("category", "general"), r.get("active", 1)),
            )
        counts["rules"] = len(data.get("trade_rules", []))

        # Import journal
        for j in data.get("journal", []):
            if not j.get("content") or not j.get("trade_date"):
                continue
            await db.execute(
                "INSERT OR IGNORE INTO journal (trade_date, content) VALUES (?, ?)",
                (j["trade_date"], j["content"]),
            )
        counts["journal"] = len(data.get("journal", []))

        await db.commit()
    finally:
        await db.close()

    return {"imported": counts}
