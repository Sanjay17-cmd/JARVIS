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
    marker = re.search(r"\b(?:in|for)\s+(.+)", text)
    if not marker:
        return None
    duration = marker.group(1)
    pattern = r"(\d+)\s*(seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h|days?|d)\b"
    terms = re.findall(pattern, duration)
    if not terms:
        return None
    remainder = re.sub(pattern, "", duration)
    remainder = re.sub(r"\band\b|[,;]", "", remainder).strip()
    if remainder:
        return None
    scales = {
        "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
        "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
        "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
        "d": 86400, "day": 86400, "days": 86400,
    }
    seconds = sum(int(amount) * scales[unit] for amount, unit in terms)
    return _now() + seconds if seconds > 0 else None


def parse_time_expression(text: str) -> float | None:
    """
    Try relative first, then absolute formats:
    HH:MM, HH:MM AM/PM, 'tomorrow HH:MM', 'YYYY-MM-DD HH:MM'
    Returns Unix timestamp or None.
    """
    rel = parse_relative_time(text)
    if rel:
        return rel

    now = datetime.now().astimezone()
    text_lower = text.lower().strip()

    # "tomorrow at HH:MM" or "tomorrow HH:MM"
    tom_m = re.search(r"tomorrow\s+(?:at\s+)?(\d{1,2}):(\d{2})\s*(am|pm)?", text_lower)
    if tom_m:
        h, mi = int(tom_m.group(1)), int(tom_m.group(2))
        ap = tom_m.group(3)
        if mi > 59 or (ap and not 1 <= h <= 12) or (not ap and h > 23):
            return None
        if ap == "pm" and h < 12: h += 12
        if ap == "am" and h == 12: h = 0
        dt = (now + timedelta(days=1)).replace(hour=h, minute=mi, second=0, microsecond=0)
        return dt.timestamp()

    # HH:MM today
    hm = re.search(r"(\d{1,2}):(\d{2})\s*(am|pm)?", text_lower)
    if hm:
        h, mi = int(hm.group(1)), int(hm.group(2))
        ap = hm.group(3)
        if mi > 59 or (ap and not 1 <= h <= 12) or (not ap and h > 23):
            return None
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


def _next_recurrence(due: float, recurrence: str, now: float | None = None) -> float:
    """Calculate next due timestamp for a recurring item."""
    now = _now() if now is None else now
    if recurrence == "daily":
        next_due = datetime.fromtimestamp(due).astimezone()
        while next_due.timestamp() <= now:
            next_due += timedelta(days=1)
        return next_due.timestamp()
    elif recurrence == "weekly":
        next_due = datetime.fromtimestamp(due).astimezone()
        while next_due.timestamp() <= now:
            next_due += timedelta(days=7)
        return next_due.timestamp()
    elif recurrence == "weekdays":
        dt = datetime.fromtimestamp(due).astimezone()
        while dt.timestamp() <= now or dt.weekday() >= 5:
            dt += timedelta(days=1)
        return dt.timestamp()
    elif recurrence.startswith("interval:"):
        try:
            interval = int(recurrence.partition(":")[2])
        except ValueError:
            return due
        if interval <= 0:
            return due
        while due <= now:
            due += interval
        return due
    return due


# ── Reminder CRUD ─────────────────────────────────────────────────────────────

def add_reminder(
    title: str,
    due_at: float,
    description: str = "",
    recurrence: str = "",
    task_id: int | None = None,
    source_key: str = "",
) -> int:
    """Insert a reminder. Returns the new row id."""
    cur = db.execute(
        "INSERT INTO reminders "
        "(title,description,created_at,due_at,recurrence,task_id,source_key) "
        "VALUES (?,?,?,?,?,?,?)",
        (title, description, _now(), due_at, recurrence, task_id, source_key),
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
    db.execute("UPDATE reminders SET completed=1,status='completed' WHERE id=?", (rid,))
    db.commit()

def snooze_reminder(rid: int, minutes: int = 10, seconds: int | None = None) -> None:
    delay = seconds if seconds is not None else minutes * 60
    if delay <= 0:
        raise ValueError("Snooze duration must be positive.")
    snooze_until = _now() + delay
    row = db.execute(
        "SELECT recurrence FROM reminders WHERE id=?", (rid,)
    ).fetchone()
    if row and str(row["recurrence"]).startswith("interval:"):
        db.execute(
            "UPDATE reminders SET due_at=?,snoozed_until=0,notified=0,status='snoozed' WHERE id=?",
            (snooze_until, rid),
        )
    else:
        db.execute(
            "UPDATE reminders SET snoozed_until=?,notified=0,status='snoozed' WHERE id=?",
            (snooze_until, rid),
        )
    db.commit()
    log.info("Reminder %d snoozed %d min", rid, minutes)


def acknowledge_recurring_reminder(rid: int) -> None:
    db.execute(
        "UPDATE reminders SET status='scheduled' WHERE id=? AND recurrence LIKE 'interval:%'",
        (rid,),
    )
    db.commit()


def delete_reminder(rid: int) -> None:
    db.execute("DELETE FROM reminders WHERE id=?", (rid,))
    db.commit()


def dismiss_reminder(rid: int) -> None:
    db.execute(
        "UPDATE reminders SET enabled=0,status='dismissed' WHERE id=?",
        (rid,),
    )
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


def edit_alarm(aid: int, **fields) -> None:
    allowed = {"title", "due_at", "recurrence", "sound", "enabled"}
    updates = {key: value for key, value in fields.items() if key in allowed}
    if not updates:
        return
    updates["notified"] = 0
    updates["dismissed"] = 0
    updates["status"] = "scheduled"
    columns = ", ".join(f"{key}=?" for key in updates)
    db.execute(
        f"UPDATE alarms SET {columns} WHERE id=?",
        (*updates.values(), aid),
    )
    db.commit()


def delete_alarm(aid: int) -> None:
    db.execute("DELETE FROM alarms WHERE id=?", (aid,))
    db.commit()


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
        now = _now()
        base_due = row["due_at"]
        if base_due >= now:
            if row["recurrence"] == "daily":
                base_due += 86400
            elif row["recurrence"] == "weekly":
                base_due += 7 * 86400
            elif row["recurrence"] == "weekdays":
                base_due += 86400
        next_due = _next_recurrence(base_due, row["recurrence"], now)
        db.execute(
            "UPDATE alarms SET due_at=?, notified=0,status='scheduled' WHERE id=?",
            (next_due, aid),
        )
    else:
        db.execute(
            "UPDATE alarms SET dismissed=1,status='dismissed' WHERE id=?",
            (aid,),
        )
    db.commit()


def snooze_alarm(aid: int, minutes: int = 5, seconds: int | None = None) -> None:
    delay = seconds if seconds is not None else minutes * 60
    if delay <= 0:
        raise ValueError("Snooze duration must be positive.")
    new_due = _now() + delay
    db.execute(
        "UPDATE alarms SET due_at=?, notified=0,status='snoozed' WHERE id=?",
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
            next_due = _next_recurrence(r["due_at"], r["recurrence"], now)
            db.execute(
                "UPDATE reminders SET due_at=?, notified=0,status='scheduled' WHERE id=?",
                (next_due, r["id"]),
            )
        else:
            db.execute(
                "UPDATE reminders SET notified=1,status='triggered' WHERE id=?",
                (r["id"],),
            )

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
        db.execute(
            "UPDATE alarms SET notified=1,status='triggered' WHERE id=?",
            (a["id"],),
        )

    if due_events:
        db.commit()
        log.info("Scheduler tick: %d due events", len(due_events))

    return due_events


def format_due(ts: float) -> str:
    """Human-readable relative time string for display."""
    delta = ts - _now()
    if delta < 0:
        return "overdue"
    if delta < 0:
        return "overdue"
    if delta < 60:
        return f"in {max(1, int(delta))} sec"
    if delta < 3600:
        return f"in {int(delta//60)} min"
    if delta < 86400:
        h = int(delta // 3600)
        return f"in {h} hr{'s' if h>1 else ''}"
    d = int(delta // 86400)
    return f"in {d} day{'s' if d>1 else ''}"
