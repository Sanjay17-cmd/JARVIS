"""
scheduling/database.py — SQLite persistence layer for reminders, alarms and tasks.

Single shared connection per process. Thread-safe via check_same_thread=False
with explicit locking for write operations.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
import uuid
import time
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
        status      TEXT    DEFAULT 'scheduled',
        channel     TEXT    DEFAULT 'ui',
        task_id     INTEGER DEFAULT NULL,
        source_key  TEXT    DEFAULT ''
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
        notified    INTEGER DEFAULT 0,
        status      TEXT    DEFAULT 'scheduled'
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
        conversation_id TEXT NOT NULL DEFAULT 'legacy',
        role        TEXT    NOT NULL CHECK (role IN ('user', 'assistant')),
        content     TEXT    NOT NULL,
        created_at  REAL    NOT NULL
    );
    CREATE TABLE IF NOT EXISTS conversations (
        id          TEXT PRIMARY KEY,
        title       TEXT NOT NULL DEFAULT 'New chat',
        created_at  REAL NOT NULL,
        updated_at  REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS app_state (
        key         TEXT PRIMARY KEY,
        value       TEXT NOT NULL
    );
    """)
    columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(conversation_messages)")
    }
    if "conversation_id" not in columns:
        conn.execute(
            "ALTER TABLE conversation_messages ADD COLUMN "
            "conversation_id TEXT NOT NULL DEFAULT 'legacy'"
        )
    for table in ("reminders", "alarms"):
        table_columns = {
            row["name"] for row in conn.execute(f"PRAGMA table_info({table})")
        }
        if "status" not in table_columns:
            conn.execute(
                f"ALTER TABLE {table} ADD COLUMN status TEXT NOT NULL DEFAULT 'scheduled'"
            )
    reminder_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(reminders)")
    }
    if "source_key" not in reminder_columns:
        conn.execute(
            "ALTER TABLE reminders ADD COLUMN source_key TEXT NOT NULL DEFAULT ''"
        )
    conn.execute(
        "INSERT OR IGNORE INTO conversations (id, title, created_at, updated_at) "
        "SELECT 'legacy', 'Previous conversation', "
        "COALESCE(MIN(created_at), ?), COALESCE(MAX(created_at), ?) "
        "FROM conversation_messages WHERE conversation_id='legacy' "
        "HAVING COUNT(*) > 0",
        (0.0, 0.0),
    )
    conn.execute(
        "INSERT OR IGNORE INTO conversations (id, title, created_at, updated_at) "
        "SELECT DISTINCT conversation_id, 'Previous conversation', "
        "MIN(created_at), MAX(created_at) FROM conversation_messages "
        "GROUP BY conversation_id"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_conversation_messages "
        "ON conversation_messages(conversation_id, created_at, id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_conversations_updated "
        "ON conversations(updated_at DESC)"
    )
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


def active_conversation_id() -> str:
    with _lock:
        conn = get_conn()
        row = conn.execute(
            "SELECT value FROM app_state WHERE key='active_conversation_id'"
        ).fetchone()
        if row:
            exists = conn.execute(
                "SELECT 1 FROM conversations WHERE id=?", (row["value"],)
            ).fetchone()
            if exists:
                return str(row["value"])
        legacy = conn.execute(
            "SELECT 1 FROM conversation_messages WHERE conversation_id='legacy' LIMIT 1"
        ).fetchone()
        conversation_id = "legacy" if legacy else uuid.uuid4().hex
        now = time.time()
        conn.execute(
            "INSERT OR IGNORE INTO conversations (id,title,created_at,updated_at) "
            "VALUES (?, ?, ?, ?)",
            (conversation_id, "Previous conversation" if legacy else "New chat", now, now),
        )
        conn.execute(
            "INSERT OR REPLACE INTO app_state (key,value) VALUES "
            "('active_conversation_id',?)",
            (conversation_id,),
        )
        conn.commit()
        return conversation_id


def create_conversation(title: str = "New chat", activate: bool = True) -> str:
    conversation_id = uuid.uuid4().hex
    now = time.time()
    with _lock:
        conn = get_conn()
        conn.execute(
            "INSERT INTO conversations (id,title,created_at,updated_at) VALUES (?,?,?,?)",
            (conversation_id, title.strip() or "New chat", now, now),
        )
        if activate:
            conn.execute(
                "INSERT OR REPLACE INTO app_state (key,value) VALUES "
                "('active_conversation_id',?)",
                (conversation_id,),
            )
        conn.commit()
    return conversation_id


def set_active_conversation(conversation_id: str) -> None:
    with _lock:
        conn = get_conn()
        if not conn.execute(
            "SELECT 1 FROM conversations WHERE id=?", (conversation_id,)
        ).fetchone():
            raise ValueError(f"Conversation '{conversation_id}' does not exist.")
        conn.execute(
            "INSERT OR REPLACE INTO app_state (key,value) VALUES "
            "('active_conversation_id',?)",
            (conversation_id,),
        )
        conn.commit()


def list_conversations() -> list[dict]:
    with _lock:
        rows = get_conn().execute(
            "SELECT id,title,created_at,updated_at FROM conversations "
            "ORDER BY updated_at DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def rename_conversation(conversation_id: str, title: str) -> None:
    title = title.strip()
    if not title:
        raise ValueError("Conversation title cannot be empty.")
    with _lock:
        conn = get_conn()
        cursor = conn.execute(
            "UPDATE conversations SET title=?,updated_at=? WHERE id=?",
            (title, time.time(), conversation_id),
        )
        if cursor.rowcount == 0:
            raise ValueError(f"Conversation '{conversation_id}' does not exist.")
        conn.commit()


def delete_conversation(conversation_id: str) -> None:
    with _lock:
        conn = get_conn()
        conn.execute(
            "DELETE FROM conversation_messages WHERE conversation_id=?",
            (conversation_id,),
        )
        conn.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))
        active = conn.execute(
            "SELECT value FROM app_state WHERE key='active_conversation_id'"
        ).fetchone()
        if active and active["value"] == conversation_id:
            conn.execute(
                "DELETE FROM app_state WHERE key='active_conversation_id'"
            )
        conn.commit()


def save_conversation_message(
    role: str,
    content: str,
    created_at: float,
    conversation_id: str | None = None,
) -> None:
    if role not in {"user", "assistant"}:
        raise ValueError(f"Unsupported conversation role: {role}")
    if not content.strip():
        raise ValueError("Conversation message cannot be empty.")
    conversation_id = conversation_id or active_conversation_id()
    with _lock:
        conn = get_conn()
        if not conn.execute(
            "SELECT 1 FROM conversations WHERE id=?", (conversation_id,)
        ).fetchone():
            raise ValueError(f"Conversation '{conversation_id}' does not exist.")
        conn.execute(
            "INSERT INTO conversation_messages "
            "(conversation_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (conversation_id, role, content, created_at),
        )
        conversation = conn.execute(
            "SELECT title FROM conversations WHERE id=?", (conversation_id,)
        ).fetchone()
        title = conversation["title"]
        if role == "user" and title == "New chat":
            title = content.strip().splitlines()[0][:60]
        conn.execute(
            "UPDATE conversations SET title=?, updated_at=? WHERE id=?",
            (title, created_at, conversation_id),
        )
        conn.execute(
            "DELETE FROM conversation_messages WHERE id NOT IN "
            "(SELECT id FROM conversation_messages ORDER BY id DESC LIMIT 2000)"
        )
        conn.commit()


def load_conversation_history(
    limit: int = 200,
    conversation_id: str | None = None,
) -> list[dict]:
    if limit < 1:
        raise ValueError("Conversation history limit must be positive")
    conversation_id = conversation_id or active_conversation_id()
    with _lock:
        rows = get_conn().execute(
            "SELECT role, content, created_at FROM "
            "(SELECT id, role, content, created_at FROM conversation_messages "
            "WHERE conversation_id=? ORDER BY id DESC LIMIT ?) ORDER BY id",
            (conversation_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def conversation_messages(conversation_id: str) -> list[dict]:
    with _lock:
        rows = get_conn().execute(
            "SELECT id,role,content,created_at FROM conversation_messages "
            "WHERE conversation_id=? ORDER BY id",
            (conversation_id,),
        ).fetchall()
    return [dict(row) for row in rows]
