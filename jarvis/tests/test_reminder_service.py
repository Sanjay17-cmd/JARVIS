"""
tests/test_reminder_service.py — Part E: reminder/alarm/scheduler tests.
Uses an in-memory SQLite DB via monkeypatching.
"""
import time
import pytest
from unittest.mock import patch


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """Each test gets its own isolated in-memory DB."""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    import jarvis.scheduling.database as db_mod
    db_mod._conn = None   # reset shared connection
    yield
    db_mod.close()
    db_mod._conn = None


from jarvis.scheduling.reminder_service import (
    add_reminder, get_reminders, get_upcoming_reminders,
    complete_reminder, snooze_reminder, delete_reminder, edit_reminder,
    add_alarm, get_alarms, dismiss_alarm, snooze_alarm,
    edit_alarm,
    tick, parse_relative_time, parse_time_expression, format_due, _now,
)


# ── Time parsing ──────────────────────────────────────────────────────────────

def test_parse_relative_minutes():
    t = parse_relative_time("in 30 minutes")
    assert abs(t - (_now() + 1800)) < 2

def test_parse_relative_hours():
    t = parse_relative_time("in 2 hours")
    assert abs(t - (_now() + 7200)) < 2

@pytest.mark.parametrize(
    ("text", "expected_seconds"),
    [
        ("in 5 seconds", 5),
        ("for 2 mins", 120),
        ("in 1 hour and 30 minutes", 5400),
    ],
)
def test_parse_short_and_combined_durations(text, expected_seconds):
    due = parse_relative_time(text)
    assert due is not None
    assert abs(due - (_now() + expected_seconds)) < 2


def test_alarm_snooze_accepts_seconds():
    aid = add_alarm("Short snooze", _now() + 1)
    snooze_alarm(aid, seconds=2)
    assert abs(get_alarms()[0]["due_at"] - (_now() + 2)) < 1

def test_parse_relative_none():
    assert parse_relative_time("tomorrow morning") is None

def test_parse_time_expression_relative():
    t = parse_time_expression("in 10 minutes")
    assert t is not None
    assert t > _now()


def test_parse_clock_time_and_reject_invalid_clock_time():
    parsed = parse_time_expression("7:30 PM")
    assert parsed is not None
    assert time.localtime(parsed).tm_hour == 19
    assert parse_time_expression("29:90 PM") is None

def test_format_due_future():
    assert "min" in format_due(_now() + 900)   # 15 min

def test_format_due_overdue():
    assert "overdue" in format_due(_now() - 60)


# ── Reminder CRUD ─────────────────────────────────────────────────────────────

def test_add_and_get_reminder():
    rid = add_reminder("Test task", _now() + 3600)
    items = get_reminders()
    assert len(items) == 1
    assert items[0]["title"] == "Test task"

def test_complete_reminder():
    rid = add_reminder("Do homework", _now() + 100)
    complete_reminder(rid)
    items = get_reminders()   # default excludes completed
    assert len(items) == 0

def test_delete_reminder():
    rid = add_reminder("Delete me", _now() + 100)
    delete_reminder(rid)
    assert len(get_reminders()) == 0

def test_snooze_reminder():
    rid = add_reminder("Snoozed", _now() + 1)
    time.sleep(0.05)
    snooze_reminder(rid, minutes=10)
    items = get_reminders()
    assert items[0]["snoozed_until"] > _now()

def test_edit_reminder():
    rid = add_reminder("Old title", _now() + 3600)
    edit_reminder(rid, title="New title")
    items = get_reminders()
    assert items[0]["title"] == "New title"

def test_upcoming_reminders_excludes_past():
    add_reminder("Past",   _now() - 100)
    add_reminder("Future", _now() + 3600)
    upcoming = get_upcoming_reminders()
    assert len(upcoming) == 1
    assert upcoming[0]["title"] == "Future"


# ── Alarm CRUD ────────────────────────────────────────────────────────────────

def test_add_and_get_alarm():
    add_alarm("Wake up", _now() + 3600)
    alarms = get_alarms()
    assert len(alarms) == 1
    assert alarms[0]["title"] == "Wake up"

def test_dismiss_alarm():
    aid = add_alarm("One-time", _now() + 1)
    dismiss_alarm(aid)
    assert len(get_alarms()) == 0

def test_dismiss_recurring_alarm_reschedules():
    aid = add_alarm("Daily", _now() + 1, recurrence="daily")
    dismiss_alarm(aid)
    alarms = get_alarms()
    assert len(alarms) == 1
    assert alarms[0]["due_at"] > _now() + 80000   # rescheduled ~24h out

def test_snooze_alarm():
    aid = add_alarm("Alarm", _now() + 1)
    snooze_alarm(aid, minutes=5)
    alarms = get_alarms()
    assert alarms[0]["due_at"] > _now() + 200   # snoozed ~5 min


def test_edit_alarm_resets_delivery_state():
    aid = add_alarm("Old", _now() - 1)
    tick()
    new_due = _now() + 30
    edit_alarm(aid, title="Updated", due_at=new_due)
    alarm = get_alarms()[0]
    assert alarm["title"] == "Updated"
    assert alarm["due_at"] == new_due
    assert alarm["notified"] == 0
    assert alarm["status"] == "scheduled"


# ── Scheduler tick + deduplication ───────────────────────────────────────────

def test_tick_fires_due_reminder():
    add_reminder("Due now", _now() - 1)
    events = tick()
    assert len(events) == 1
    assert events[0]["type"] == "reminder"

def test_tick_does_not_fire_future():
    add_reminder("Not yet", _now() + 3600)
    assert tick() == []

def test_tick_deduplication():
    """After firing, the same reminder must NOT fire again."""
    add_reminder("Dedup test", _now() - 1)
    tick()
    second = tick()
    assert second == []

def test_tick_fires_due_alarm():
    add_alarm("Ring", _now() - 1)
    events = tick()
    assert any(e["type"] == "alarm" for e in events)

def test_tick_respects_snooze():
    rid = add_reminder("Snoozed", _now() - 1)
    snooze_reminder(rid, minutes=5)
    assert tick() == []

def test_recurring_reminder_reschedules_after_tick():
    add_reminder("Daily check", _now() - 1, recurrence="daily")
    tick()
    items = get_reminders()
    assert items[0]["due_at"] > _now() + 80000   # ~24h later


def test_interval_reminder_reschedules_once_and_records_triggered_event():
    rid = add_reminder(
        "Frequent test", _now() - 2, recurrence="interval:10",
        source_key="test:interval",
    )
    events = tick()
    assert len(events) == 1
    assert events[0]["id"] == rid
    assert events[0]["source_key"] == "test:interval"
    assert tick() == []
    updated = get_reminders()[0]
    assert updated["due_at"] > _now()
    assert updated["status"] == "scheduled"
