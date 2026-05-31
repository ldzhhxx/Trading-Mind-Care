"""Database initialization and connection management."""
import os
import sys
import platform
import aiosqlite

_db_path: str | None = None


def get_db_path() -> str:
    global _db_path
    if _db_path:
        return _db_path

    if platform.system() == "Windows":
        base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        directory = os.path.join(base, "TradingMindCare")
    else:
        directory = os.path.expanduser("~/.trading_mind_care")

    os.makedirs(directory, exist_ok=True)
    _db_path = os.path.join(directory, "mind_care.db")
    return _db_path


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(get_db_path())
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


async def init_db():
    db = await get_db()
    try:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS sys_config (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS plans (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_type  TEXT NOT NULL CHECK(plan_type IN ('today', 'tomorrow')),
            content    TEXT NOT NULL,
            done       INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            trade_date TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS reviews (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_date  TEXT NOT NULL,
            pnl         REAL,
            emotion_log TEXT NOT NULL,
            ai_critique TEXT,
            created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS vulnerability_matrix (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            tag         TEXT NOT NULL UNIQUE,
            weight      REAL NOT NULL DEFAULT 1.0,
            hit_count   INTEGER NOT NULL DEFAULT 0,
            last_hit_at TEXT,
            description TEXT
        );

        CREATE TABLE IF NOT EXISTS plan_templates (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL UNIQUE
        );

        CREATE INDEX IF NOT EXISTS idx_plans_date ON plans(trade_date);
        CREATE INDEX IF NOT EXISTS idx_reviews_date ON reviews(trade_date);
        """)

        # Migrations for existing databases
        try:
            await db.execute("ALTER TABLE plans ADD COLUMN done INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass  # column already exists

        # Insert defaults if not exist
        defaults = [
            ("base_url", "https://token-plan-cn.xiaomimimo.com/v1"),
            ("api_key", ""),
            ("model_name", ""),
            ("feishu_webhook", ""),
            ("notify_time", "08:30"),
            ("last_decay_date", ""),
            ("last_notify_date", ""),
        ]
        for key, value in defaults:
            await db.execute(
                "INSERT OR IGNORE INTO sys_config (key, value) VALUES (?, ?)",
                (key, value),
            )
        await db.commit()
    finally:
        await db.close()
