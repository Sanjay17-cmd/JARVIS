"""SQLite-backed AI cache, memory, summaries, and usage statistics."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import uuid
from typing import Any

from jarvis.scheduling import database as db

CACHE_POLICY_VERSION = 1


def initialize() -> None:
    with db._lock:
        conn = db.get_conn()
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS ai_response_cache (
            cache_key TEXT PRIMARY KEY,
            normalized_prompt TEXT NOT NULL,
            cache_policy INTEGER NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            context_fingerprint TEXT NOT NULL,
            response TEXT NOT NULL,
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ai_cache_expiry
            ON ai_response_cache(expires_at);
        CREATE TABLE IF NOT EXISTS ai_conversation_summaries (
            conversation_id TEXT PRIMARY KEY,
            summary TEXT NOT NULL,
            updated_at REAL NOT NULL,
            summarized_through_id INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS ai_memories (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ai_usage (
            id TEXT PRIMARY KEY,
            request_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            status TEXT NOT NULL,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            cache_hit INTEGER NOT NULL DEFAULT 0,
            elapsed_ms INTEGER NOT NULL DEFAULT 0,
            error_category TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ai_usage_created
            ON ai_usage(created_at DESC);
        CREATE TABLE IF NOT EXISTS ai_model_catalog (
            provider TEXT NOT NULL,
            model_id TEXT NOT NULL,
            display_name TEXT NOT NULL,
            is_free INTEGER NOT NULL DEFAULT 0,
            fetched_at REAL NOT NULL,
            PRIMARY KEY(provider, model_id)
        );
        """)
        summary_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(ai_conversation_summaries)")
        }
        if "summarized_through_id" not in summary_columns:
            conn.execute(
                "ALTER TABLE ai_conversation_summaries "
                "ADD COLUMN summarized_through_id INTEGER NOT NULL DEFAULT 0"
            )
        conn.commit()
        try:
            conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS ai_memory_fts USING fts5(
                memory_id UNINDEXED, content
            )
            """)
            conn.commit()
        except sqlite3.OperationalError:
            # FTS5 may be unavailable; memory search uses a parameterized fallback.
            pass


def fingerprint(*parts: str) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def normalize_prompt(text: str) -> str:
    return " ".join(text.casefold().split())


def get_cached(cache_key: str) -> dict[str, Any] | None:
    initialize()
    now = time.time()
    conn = db.get_conn()
    with db._lock:
        row = conn.execute(
            "SELECT provider,model,response,expires_at FROM ai_response_cache "
            "WHERE cache_key=? AND cache_policy=? AND expires_at>?",
            (cache_key, CACHE_POLICY_VERSION, now),
        ).fetchone()
        conn.execute("DELETE FROM ai_response_cache WHERE expires_at<=?", (now,))
        conn.commit()
    return dict(row) if row else None


def save_cached(
    cache_key: str,
    prompt: str,
    provider: str,
    model: str,
    context_fingerprint: str,
    response: str,
    ttl_seconds: int,
) -> None:
    initialize()
    now = time.time()
    conn = db.get_conn()
    with db._lock:
        conn.execute(
            "INSERT OR REPLACE INTO ai_response_cache "
            "(cache_key,normalized_prompt,cache_policy,provider,model,"
            "context_fingerprint,response,created_at,expires_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                cache_key, normalize_prompt(prompt), CACHE_POLICY_VERSION,
                provider, model, context_fingerprint, response, now,
                now + max(1, ttl_seconds),
            ),
        )
        conn.commit()


def clear_cache() -> int:
    initialize()
    conn = db.get_conn()
    with db._lock:
        count = conn.execute("SELECT COUNT(*) FROM ai_response_cache").fetchone()[0]
        conn.execute("DELETE FROM ai_response_cache")
        conn.commit()
    return int(count)


def save_summary(
    conversation_id: str, summary: str, summarized_through_id: int = 0
) -> None:
    initialize()
    conn = db.get_conn()
    with db._lock:
        conn.execute(
            "INSERT OR REPLACE INTO ai_conversation_summaries "
            "(conversation_id,summary,updated_at,summarized_through_id) "
            "VALUES (?,?,?,?)",
            (conversation_id, summary, time.time(), summarized_through_id),
        )
        conn.commit()


def get_summary(conversation_id: str) -> str:
    initialize()
    row = db.execute(
        "SELECT summary FROM ai_conversation_summaries WHERE conversation_id=?",
        (conversation_id,),
    ).fetchone()
    return str(row["summary"]) if row else ""


def update_extractive_summary(
    conversation_id: str,
    messages: list[dict[str, Any]],
    keep_recent: int,
    max_chars: int = 2200,
) -> str:
    initialize()
    older = messages[:-keep_recent] if keep_recent > 0 else messages
    if not older:
        return get_summary(conversation_id)
    row = db.execute(
        "SELECT summary,summarized_through_id FROM ai_conversation_summaries "
        "WHERE conversation_id=?",
        (conversation_id,),
    ).fetchone()
    previous = str(row["summary"]) if row else ""
    summarized_through = int(row["summarized_through_id"]) if row else 0
    additions = [message for message in older if int(message["id"]) > summarized_through]
    if not additions:
        return previous
    excerpts = []
    for message in additions:
        content = " ".join(str(message["content"]).split())
        if content:
            excerpts.append(f"{message['role']}: {content[:240]}")
    combined = "\n".join(([previous] if previous else []) + excerpts)
    summary = combined[-max_chars:]
    save_summary(conversation_id, summary, int(additions[-1]["id"]))
    return summary


def add_memory(content: str, memory_id: str | None = None) -> str:
    content = " ".join(content.split()).strip()
    if not content:
        raise ValueError("Memory cannot be empty.")
    initialize()
    memory_id = memory_id or uuid.uuid4().hex
    now = time.time()
    conn = db.get_conn()
    with db._lock:
        conn.execute(
            "INSERT OR REPLACE INTO ai_memories "
            "(id,content,created_at,updated_at) VALUES (?,?,?,?)",
            (memory_id, content, now, now),
        )
        try:
            conn.execute("DELETE FROM ai_memory_fts WHERE memory_id=?", (memory_id,))
            conn.execute(
                "INSERT INTO ai_memory_fts(memory_id,content) VALUES (?,?)",
                (memory_id, content),
            )
        except sqlite3.OperationalError:
            pass
        conn.commit()
    return memory_id


def list_memories() -> list[dict[str, Any]]:
    initialize()
    rows = db.execute(
        "SELECT id,content,created_at,updated_at FROM ai_memories "
        "ORDER BY updated_at DESC"
    ).fetchall()
    return [dict(row) for row in rows]


def search_memories(query: str, limit: int = 4) -> list[str]:
    initialize()
    stop_words = {
        "about", "after", "also", "and", "are", "can", "could", "for", "from",
        "have", "how", "into", "just", "me", "my", "please", "should", "that",
        "the", "their", "them", "there", "this", "what", "when", "where", "which",
        "who", "why", "with", "would", "you", "your",
    }
    terms = [
        term for term in re.findall(r"\w+", query.casefold())
        if len(term) > 2 and term not in stop_words
    ][:8]
    if not terms:
        return []
    conn = db.get_conn()
    with db._lock:
        try:
            rows = conn.execute(
                "SELECT m.content FROM ai_memory_fts f "
                "JOIN ai_memories m ON m.id=f.memory_id "
                "WHERE ai_memory_fts MATCH ? ORDER BY rank LIMIT ?",
                (" OR ".join(terms), limit),
            ).fetchall()
        except sqlite3.OperationalError:
            like_query = "%" + "%".join(terms) + "%"
            rows = conn.execute(
                "SELECT content FROM ai_memories WHERE lower(content) LIKE ? "
                "ORDER BY updated_at DESC LIMIT ?",
                (like_query, limit),
            ).fetchall()
    return [str(row["content"]) for row in rows]


def delete_memory(memory_id: str) -> None:
    initialize()
    conn = db.get_conn()
    with db._lock:
        conn.execute("DELETE FROM ai_memories WHERE id=?", (memory_id,))
        try:
            conn.execute("DELETE FROM ai_memory_fts WHERE memory_id=?", (memory_id,))
        except sqlite3.OperationalError:
            pass
        conn.commit()


def record_usage(
    request_id: str,
    provider: str,
    model: str,
    status: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_hit: bool = False,
    elapsed_ms: int = 0,
    error_category: str = "",
) -> None:
    initialize()
    db.execute(
        "INSERT INTO ai_usage "
        "(id,request_id,provider,model,status,input_tokens,output_tokens,"
        "cache_hit,elapsed_ms,error_category,created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            uuid.uuid4().hex, request_id, provider, model, status,
            max(0, input_tokens), max(0, output_tokens), int(cache_hit),
            max(0, elapsed_ms), error_category, time.time(),
        ),
    )
    db.commit()


def usage_stats() -> dict[str, int]:
    initialize()
    row = db.execute(
        "SELECT COUNT(DISTINCT request_id) AS requests,"
        "COUNT(*) AS attempts,"
        "COALESCE(SUM(input_tokens),0) AS input_tokens,"
        "COALESCE(SUM(output_tokens),0) AS output_tokens,"
        "COALESCE(SUM(cache_hit),0) AS cache_hits,"
        "COALESCE(SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END),0) AS failures,"
        "COALESCE(SUM(CASE WHEN cache_hit=1 THEN input_tokens+output_tokens ELSE 0 END),0) "
        "AS estimated_saved_tokens "
        "FROM ai_usage"
    ).fetchone()
    return dict(row)


def save_model_catalog(provider: str, models: list[dict[str, Any]]) -> None:
    initialize()
    now = time.time()
    conn = db.get_conn()
    with db._lock:
        conn.execute("DELETE FROM ai_model_catalog WHERE provider=?", (provider,))
        conn.executemany(
            "INSERT INTO ai_model_catalog(provider,model_id,display_name,is_free,fetched_at) "
            "VALUES (?,?,?,?,?)",
            [
                (
                    provider, model["id"], model.get("name", model["id"]),
                    int(bool(model.get("free"))), now,
                )
                for model in models
            ],
        )
        conn.commit()


def cached_model_catalog(provider: str, max_age: int = 3600) -> list[dict[str, Any]]:
    initialize()
    rows = db.execute(
        "SELECT model_id,display_name,is_free,fetched_at FROM ai_model_catalog "
        "WHERE provider=? AND fetched_at>=? ORDER BY display_name",
        (provider, time.time() - max_age),
    ).fetchall()
    return [
        {"id": row["model_id"], "name": row["display_name"], "free": bool(row["is_free"])}
        for row in rows
    ]


def estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4) if text else 0
