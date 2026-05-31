"""Database initialization and connection management."""
import os
import sys
import logging
import platform
import aiosqlite

logger = logging.getLogger(__name__)

_db_path: str | None = None


def get_db_path() -> str:
    """Get database file path, creating directory if needed."""
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
    """Open a new database connection with WAL mode and foreign keys."""
    db = await aiosqlite.connect(get_db_path(), timeout=30.0)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    await db.execute("PRAGMA busy_timeout=5000")
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
            description TEXT,
            category    TEXT NOT NULL DEFAULT '未分类'
        );

        CREATE TABLE IF NOT EXISTS plan_templates (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS trade_rules (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            rule       TEXT NOT NULL,
            category   TEXT NOT NULL DEFAULT 'general',
            active     INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS journal (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_date TEXT NOT NULL,
            content    TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        );

        CREATE INDEX IF NOT EXISTS idx_plans_date ON plans(trade_date);
        CREATE INDEX IF NOT EXISTS idx_reviews_date ON reviews(trade_date);
        CREATE INDEX IF NOT EXISTS idx_journal_date ON journal(trade_date);
        """)

        # Run migrations
        await _run_migrations(db)

        # Insert defaults if not exist
        defaults = [
            ("base_url", "https://token-plan-cn.xiaomimimo.com/v1"),
            ("api_key", ""),
            ("model_name", ""),
            ("feishu_webhook", ""),
            ("notify_time", "08:30"),
            ("last_decay_date", ""),
            ("last_notify_date", ""),
            ("decay_rate", "0.98"),
            ("reminder_time", "20:00"),
            ("schema_version", "3"),
        ]
        for key, value in defaults:
            await db.execute(
                "INSERT OR IGNORE INTO sys_config (key, value) VALUES (?, ?)",
                (key, value),
            )
        await db.commit()
    finally:
        await db.close()


async def _run_migrations(db):
    """Run pending schema migrations."""
    # Get current version
    try:
        cursor = await db.execute("SELECT MAX(version) as v FROM schema_migrations")
        row = await cursor.fetchone()
        current = row["v"] or 0
    except Exception:
        current = 0

    migrations = [
        # Migration 1: Add mood column to reviews
        (1, "ALTER TABLE reviews ADD COLUMN mood INTEGER"),
        # Migration 2: Add category to vulnerability_matrix
        (2, "ALTER TABLE vulnerability_matrix ADD COLUMN category TEXT NOT NULL DEFAULT '未分类'"),
        # Migration 3: Add done column to plans
        (3, "ALTER TABLE plans ADD COLUMN done INTEGER NOT NULL DEFAULT 0"),
        # Migration 4: Goals table
        (4, """CREATE TABLE IF NOT EXISTS goals (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            title        TEXT NOT NULL,
            goal_type    TEXT NOT NULL DEFAULT 'monthly',
            target_month TEXT NOT NULL,
            status       TEXT NOT NULL DEFAULT 'active',
            created_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            completed_at TEXT
        )"""),
        # Migration 5: Index on goals
        (5, "CREATE INDEX IF NOT EXISTS idx_goals_month ON goals(target_month)"),
        # Migration 6: Performance indexes
        (6, "CREATE INDEX IF NOT EXISTS idx_reviews_pnl ON reviews(pnl)"),
        (7, "CREATE INDEX IF NOT EXISTS idx_reviews_mood ON reviews(mood)"),
        (8, "CREATE INDEX IF NOT EXISTS idx_reviews_created ON reviews(created_at)"),
        (9, "CREATE INDEX IF NOT EXISTS idx_plans_type_date ON plans(plan_type, trade_date)"),
        (10, "CREATE INDEX IF NOT EXISTS idx_vuln_weight ON vulnerability_matrix(weight DESC)"),
        (11, "CREATE INDEX IF NOT EXISTS idx_goals_status ON goals(status)"),
    ]

    for version, sql in migrations:
        if version <= current:
            continue
        try:
            await db.execute(sql)
        except Exception:
            pass  # Column already exists from old migration style
        await db.execute(
            "INSERT OR REPLACE INTO schema_migrations (version) VALUES (?)", (version,)
        )

    await db.commit()
