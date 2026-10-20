"""
scheduling/database.py — SQLite persistence layer for reminders, alarms and tasks.

Single shared connection per process. Thread-safe via check_same_thread=False
with explicit locking for write operations.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path
import os

log = logging.getLogger(__name__)
_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _db_path() -> Path:
    base = os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming"
    p = Path(base) / "JARVIS"
    p.mkdir(parents=True, exist_ok=True)
    return p / "jarvis.db"


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(
            str(_db_path()),
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
        )
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA foreign_keys=ON")
        _create_schema(_conn)
        log.info("Database opened: %s", _db_path())
    return _conn


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS reminders (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        title       TEXT    NOT NULL,
        description TEXT    DEFAULT '',
        created_at  REAL    NOT NULL,   -- Unix timestamp
        due_at      REAL    NOT NULL,   -- Unix timestamp
        recurrence  TEXT    DEFAULT '', -- '' | 'daily' | 'weekly' | 'weekdays'
        enabled     INTEGER DEFAULT 1,
        snoozed_until REAL  DEFAULT 0,
        completed   INTEGER DEFAULT 0,
        notified    INTEGER DEFAULT 0,  -- dedup: 1 after first delivery
        channel     TEXT    DEFAULT 'ui',
        task_id     INTEGER DEFAULT NULL
    );

    CREATE TABLE IF NOT EXISTS alarms (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        title       TEXT    NOT NULL,
        due_at      REAL    NOT NULL,
        recurrence  TEXT    DEFAULT '',  -- '' | 'daily' | 'weekdays' | 'mon,tue,...'
        enabled     INTEGER DEFAULT 1,
        sound       INTEGER DEFAULT 1,
        snooze_min  INTEGER DEFAULT 5,
        dismissed   INTEGER DEFAULT 0,
        notified    INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS tasks (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        title           TEXT    NOT NULL,
        description     TEXT    DEFAULT '',
        created_at      REAL    NOT NULL,
        deadline        REAL    DEFAULT NULL,
        priority        INTEGER DEFAULT 1,  -- 1=low 2=med 3=high
        status          TEXT    DEFAULT 'todo',  -- todo|in_progress|done
        estimated_min   INTEGER DEFAULT 0,
        completed_at    REAL    DEFAULT NULL,
        recurrence      TEXT    DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS conversation_messages (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        role        TEXT    NOT NULL CHECK (role IN ('user', 'assistant')),
        content     TEXT    NOT NULL,
        created_at  REAL    NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_conversation_created
        ON conversation_messages(created_at, id);
    """)
    conn.commit()


def close() -> None:
    global _conn
    if _conn:
        _conn.close()
        _conn = None
        log.info("Database closed.")


def execute(sql: str, params: tuple = ()) -> sqlite3.Cursor:
    with _lock:
        return get_conn().execute(sql, params)


def executemany(sql: str, params_list: list) -> None:
    with _lock:
        get_conn().executemany(sql, params_list)
        get_conn().commit()


def commit() -> None:
    with _lock:
        get_conn().commit()


def save_conversation_message(role: str, content: str, created_at: float) -> None:
    if role not in {"user", "assistant"}:
        raise ValueError(f"Unsupported conversation role: {role}")
    with _lock:
        conn = get_conn()
        conn.execute(
            "INSERT INTO conversation_messages (role, content, created_at) "
            "VALUES (?, ?, ?)",
            (role, content, created_at),
        )
        conn.execute(
            "DELETE FROM conversation_messages WHERE id NOT IN "
            "(SELECT id FROM conversation_messages ORDER BY id DESC LIMIT 2000)"
        )
        conn.commit()


def load_conversation_history(limit: int = 200) -> list[dict]:
    if limit < 1:
        raise ValueError("Conversation history limit must be positive")
    with _lock:
        rows = get_conn().execute(
            "SELECT role, content, created_at FROM "
            "(SELECT id, role, content, created_at FROM conversation_messages "
            "ORDER BY id DESC LIMIT ?) ORDER BY id",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]
