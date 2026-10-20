"""
scheduling/reminder_service.py — CRUD + scheduler for reminders and alarms.

Features:
  • Add / edit / delete / snooze / complete reminders
  • Add / dismiss / snooze alarms  
  • Recurrence: daily, weekly, weekdays
  • Relative time parsing: "in 30 minutes", "in 2 hours"
  • Due-event check via tick() — called by a QTimer in the app
  • Deduplication: notified flag prevents double-fire on restart
  • Returns structured dicts; no UI imports here
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta
from typing import Any

from jarvis.scheduling import database as db

log = logging.getLogger(__name__)


# ── Time helpers ──────────────────────────────────────────────────────────────

def _now() -> float:
    return time.time()


def parse_relative_time(text: str) -> float | None:
    """
    Parse strings like 'in 30 minutes', 'in 2 hours', 'in 1 day'.
    Returns a Unix timestamp or None if not parseable.
    """
    text = text.lower().strip()
    patterns = [
        (r"in\s+(\d+)\s+min(?:ute)?s?",  "minutes"),
        (r"in\s+(\d+)\s+hour?s?",         "hours"),
        (r"in\s+(\d+)\s+day?s?",          "days"),
        (r"in\s+(\d+)\s+sec(?:ond)?s?",   "seconds"),
    ]
    for pattern, unit in patterns:
        m = re.search(pattern, text)
        if m:
            n = int(m.group(1))
            delta = {"minutes": n*60, "hours": n*3600,
                     "days": n*86400, "seconds": n}[unit]
            return _now() + delta
    return None


def parse_time_expression(text: str) -> float | None:
    """
    Try relative first, then absolute formats:
    HH:MM, HH:MM AM/PM, 'tomorrow HH:MM', 'YYYY-MM-DD HH:MM'
    Returns Unix timestamp or None.
    """
    rel = parse_relative_time(text)
    if rel:
        return rel

    now = datetime.now()
    text_lower = text.lower().strip()

    # "tomorrow at HH:MM" or "tomorrow HH:MM"
    tom_m = re.search(r"tomorrow\s+(?:at\s+)?(\d{1,2}):(\d{2})\s*(am|pm)?", text_lower)
    if tom_m:
        h, mi = int(tom_m.group(1)), int(tom_m.group(2))
        ap = tom_m.group(3)
        if ap == "pm" and h < 12: h += 12
        if ap == "am" and h == 12: h = 0
        dt = (now + timedelta(days=1)).replace(hour=h, minute=mi, second=0, microsecond=0)
        return dt.timestamp()

    # HH:MM today
    hm = re.search(r"^(\d{1,2}):(\d{2})\s*(am|pm)?$", text_lower)
    if hm:
        h, mi = int(hm.group(1)), int(hm.group(2))
        ap = hm.group(3)
        if ap == "pm" and h < 12: h += 12
        if ap == "am" and h == 12: h = 0
        dt = now.replace(hour=h, minute=mi, second=0, microsecond=0)
        if dt.timestamp() < _now():
            dt += timedelta(days=1)   # already passed → schedule tomorrow
        return dt.timestamp()

    # YYYY-MM-DD HH:MM
    full = re.search(r"(\d{4}-\d{2}-\d{2})\s+(\d{1,2}:\d{2})", text)
    if full:
        try:
            dt = datetime.strptime(full.group(0), "%Y-%m-%d %H:%M")
            return dt.timestamp()
        except ValueError:
            pass

    return None


def _next_recurrence(due: float, recurrence: str) -> float:
    """Calculate next due timestamp for a recurring item."""
    if recurrence == "daily":
        return due + 86400
    elif recurrence == "weekly":
        return due + 7 * 86400
    elif recurrence == "weekdays":
        dt = datetime.fromtimestamp(due) + timedelta(days=1)
        while dt.weekday() >= 5:   # skip Sat/Sun
            dt += timedelta(days=1)
        return dt.timestamp()
    return due


# ── Reminder CRUD ─────────────────────────────────────────────────────────────

def add_reminder(
    title: str,
    due_at: float,
    description: str = "",
    recurrence: str = "",
) -> int:
    """Insert a reminder. Returns the new row id."""
    cur = db.execute(
        "INSERT INTO reminders (title,description,created_at,due_at,recurrence) "
        "VALUES (?,?,?,?,?)",
        (title, description, _now(), due_at, recurrence),
    )
    db.commit()
    log.info("Reminder added: '%s' due %s", title,
             datetime.fromtimestamp(due_at).strftime("%Y-%m-%d %H:%M"))
    return cur.lastrowid


def get_reminders(include_completed: bool = False) -> list[dict]:
    where = "" if include_completed else "WHERE completed=0 AND enabled=1"
    cur = db.execute(
        f"SELECT * FROM reminders {where} ORDER BY due_at ASC"
    )
    return [dict(r) for r in cur.fetchall()]


def get_upcoming_reminders(limit: int = 10) -> list[dict]:
    cur = db.execute(
        "SELECT * FROM reminders WHERE completed=0 AND enabled=1 "
        "AND due_at > ? ORDER BY due_at ASC LIMIT ?",
        (_now(), limit),
    )
    return [dict(r) for r in cur.fetchall()]


def complete_reminder(rid: int) -> None:
    db.execute("UPDATE reminders SET completed=1 WHERE id=?", (rid,))
    db.commit()


def snooze_reminder(rid: int, minutes: int = 10) -> None:
    snooze_until = _now() + minutes * 60
    db.execute(
        "UPDATE reminders SET snoozed_until=?, notified=0 WHERE id=?",
        (snooze_until, rid),
    )
    db.commit()
    log.info("Reminder %d snoozed %d min", rid, minutes)


def delete_reminder(rid: int) -> None:
    db.execute("DELETE FROM reminders WHERE id=?", (rid,))
    db.commit()


def edit_reminder(rid: int, **fields) -> None:
    allowed = {"title", "description", "due_at", "recurrence", "enabled"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    # Reset notified so the edited reminder fires again
    updates["notified"] = 0
    cols = ", ".join(f"{k}=?" for k in updates)
    db.execute(
        f"UPDATE reminders SET {cols} WHERE id=?",
        (*updates.values(), rid),
    )
    db.commit()


# ── Alarm CRUD ────────────────────────────────────────────────────────────────

def add_alarm(
    title: str,
    due_at: float,
    recurrence: str = "",
    sound: bool = True,
    snooze_min: int = 5,
) -> int:
    cur = db.execute(
        "INSERT INTO alarms (title,due_at,recurrence,sound,snooze_min) "
        "VALUES (?,?,?,?,?)",
        (title, due_at, recurrence, int(sound), snooze_min),
    )
    db.commit()
    log.info("Alarm added: '%s' at %s", title,
             datetime.fromtimestamp(due_at).strftime("%H:%M"))
    return cur.lastrowid


def get_alarms(include_dismissed: bool = False) -> list[dict]:
    where = "" if include_dismissed else "WHERE dismissed=0 AND enabled=1"
    cur = db.execute(f"SELECT * FROM alarms {where} ORDER BY due_at ASC")
    return [dict(r) for r in cur.fetchall()]


def dismiss_alarm(aid: int) -> None:
    # For non-recurring alarms mark dismissed; for recurring reschedule
    row = db.execute("SELECT * FROM alarms WHERE id=?", (aid,)).fetchone()
    if not row:
        return
    row = dict(row)
    if row["recurrence"]:
        next_due = _next_recurrence(row["due_at"], row["recurrence"])
        db.execute(
            "UPDATE alarms SET due_at=?, notified=0 WHERE id=?",
            (next_due, aid),
        )
    else:
        db.execute("UPDATE alarms SET dismissed=1 WHERE id=?", (aid,))
    db.commit()


def snooze_alarm(aid: int, minutes: int = 5) -> None:
    new_due = _now() + minutes * 60
    db.execute(
        "UPDATE alarms SET due_at=?, notified=0 WHERE id=?",
        (new_due, aid),
    )
    db.commit()


# ── Scheduler tick ────────────────────────────────────────────────────────────

def tick() -> list[dict]:
    """
    Called periodically (e.g. every 30s by a QTimer).
    Returns a list of due event dicts with a 'type' key ('reminder' or 'alarm').
    Each event is marked notified=1 immediately to prevent re-firing.
    Handles snoozed items and recurring reschedule.
    """
    now = _now()
    due_events: list[dict] = []

    # ── Reminders ────────────────────────────────────────────────────────────
    rows = db.execute(
        "SELECT * FROM reminders WHERE completed=0 AND enabled=1 "
        "AND notified=0 AND due_at<=? AND (snoozed_until=0 OR snoozed_until<=?)",
        (now, now),
    ).fetchall()

    for row in rows:
        r = dict(row)
        r["type"] = "reminder"
        due_events.append(r)
        if r["recurrence"]:
            next_due = _next_recurrence(r["due_at"], r["recurrence"])
            db.execute(
                "UPDATE reminders SET due_at=?, notified=0 WHERE id=?",
                (next_due, r["id"]),
            )
        else:
            db.execute("UPDATE reminders SET notified=1 WHERE id=?", (r["id"],))

    # ── Alarms ────────────────────────────────────────────────────────────────
    alarm_rows = db.execute(
        "SELECT * FROM alarms WHERE dismissed=0 AND enabled=1 "
        "AND notified=0 AND due_at<=?",
        (now,),
    ).fetchall()

    for row in alarm_rows:
        a = dict(row)
        a["type"] = "alarm"
        due_events.append(a)
        db.execute("UPDATE alarms SET notified=1 WHERE id=?", (a["id"],))

    if due_events:
        db.commit()
        log.info("Scheduler tick: %d due events", len(due_events))

    return due_events


def format_due(ts: float) -> str:
    """Human-readable relative time string for display."""
    delta = ts - _now()
    if delta < 0:
        return "overdue"
    if delta < 60:
        return "in less than a minute"
    if delta < 3600:
        return f"in {int(delta//60)} min"
    if delta < 86400:
        h = int(delta // 3600)
        return f"in {h} hr{'s' if h>1 else ''}"
    d = int(delta // 86400)
    return f"in {d} day{'s' if d>1 else ''}"
