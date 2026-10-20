"""
scheduling/task_service.py — Part G: Task manager CRUD.
Uses the 'tasks' table already created by database.py.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from jarvis.scheduling import database as db

log = logging.getLogger(__name__)


def _now() -> float:
    return time.time()


def add_task(title: str, description: str = "", priority: int = 1,
             deadline: float | None = None, estimated_min: int = 0) -> int:
    cur = db.execute(
        "INSERT INTO tasks (title,description,created_at,priority,deadline,estimated_min) "
        "VALUES (?,?,?,?,?,?)",
        (title, description, _now(), priority, deadline, estimated_min),
    )
    db.commit()
    _sync_task_reminder(cur.lastrowid)
    log.info("Task added: '%s' priority=%d", title, priority)
    return cur.lastrowid


def get_tasks(status: str | None = None) -> list[dict]:
    if status:
        cur = db.execute("SELECT * FROM tasks WHERE status=? ORDER BY priority DESC,created_at ASC", (status,))
    else:
        cur = db.execute("SELECT * FROM tasks WHERE status!='done' ORDER BY priority DESC,created_at ASC")
    return [dict(r) for r in cur.fetchall()]


def get_all_tasks() -> list[dict]:
    cur = db.execute("SELECT * FROM tasks ORDER BY priority DESC, created_at ASC")
    return [dict(r) for r in cur.fetchall()]


def complete_task(tid: int) -> None:
    db.execute("UPDATE tasks SET status='done', completed_at=? WHERE id=?", (_now(), tid))
    db.execute(
        "UPDATE reminders SET enabled=0,completed=1,status='completed' WHERE task_id=?",
        (tid,),
    )
    db.commit()


def set_task_status(tid: int, status: str) -> None:
    if status == "done":
        db.execute(
            "UPDATE tasks SET status=?,completed_at=COALESCE(completed_at,?) WHERE id=?",
            (status, _now(), tid),
        )
    else:
        db.execute(
            "UPDATE tasks SET status=?,completed_at=NULL WHERE id=?",
            (status, tid),
        )
    db.commit()
    _sync_task_reminder(tid)


def edit_task(tid: int, **fields) -> None:
    allowed = {"title", "description", "priority", "deadline", "estimated_min", "status"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    cols = ", ".join(f"{k}=?" for k in updates)
    db.execute(f"UPDATE tasks SET {cols} WHERE id=?", (*updates.values(), tid))
    db.commit()
    _sync_task_reminder(tid)


def delete_task(tid: int) -> None:
    db.execute("DELETE FROM reminders WHERE task_id=?", (tid,))
    db.execute("DELETE FROM tasks WHERE id=?", (tid,))
    db.commit()


def _sync_task_reminder(tid: int) -> None:
    task = db.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
    if task is None:
        return
    task = dict(task)
    linked = db.execute(
        "SELECT id FROM reminders WHERE task_id=? ORDER BY id LIMIT 1", (tid,)
    ).fetchone()
    if task["status"] == "done" or task["deadline"] is None:
        if linked:
            db.execute(
                "UPDATE reminders SET enabled=0,completed=1,status='completed' "
                "WHERE task_id=?",
                (tid,),
            )
            db.commit()
        return
    if linked:
        db.execute(
            "UPDATE reminders SET title=?,description=?,due_at=?,enabled=1,"
            "completed=0,notified=0,snoozed_until=0,status='scheduled' "
            "WHERE task_id=?",
            (task["title"], task["description"], task["deadline"], tid),
        )
        db.commit()
        return
    from jarvis.scheduling.reminder_service import add_reminder
    add_reminder(
        task["title"], task["deadline"], task["description"] or "", task_id=tid
    )


_PRIORITY_LABELS = {1: "Low", 2: "Medium", 3: "High"}
_STATUS_ICONS    = {"todo": "📋", "in_progress": "▶", "done": "✅"}


def format_task(task: dict) -> str:
    icon = _STATUS_ICONS.get(task["status"], "📋")
    pri  = _PRIORITY_LABELS.get(task["priority"], "")
    return f"{icon} [{pri}] {task['title']}"
