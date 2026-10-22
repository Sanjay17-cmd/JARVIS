import time

import pytest

from jarvis.ai.tools import ToolRegistry, get_action_history, get_tool_definitions
from jarvis.scheduling import database


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    database.close()
    monkeypatch.setenv("APPDATA", str(tmp_path))
    database._conn = None
    yield
    database.close()
    database._conn = None


class Settings:
    def __init__(self, **values):
        self.values = values
        self.save_count = 0

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value

    def save(self):
        self.save_count += 1


class Focus:
    state = "IDLE"
    is_active = False
    _remaining = 0

    def start_focus(self, duration_minutes=None):
        self.state = "FOCUSING"
        self.is_active = True
        return f"Started for {duration_minutes}."

    def stop(self):
        self.state = "IDLE"
        self.is_active = False
        return "Stopped."

    def status(self):
        return "Focus status."

    def refresh_rules(self):
        pass


def make_registry(**kwargs):
    return ToolRegistry(**kwargs)


def test_tool_names_and_schema_are_stable_and_strict():
    definitions = get_tool_definitions()
    names = [item["function"]["name"] for item in definitions]
    assert len(names) == len(set(names))
    assert {
        "task_create", "task_list", "task_update", "task_complete",
        "task_reopen", "task_add_note", "reminder_create", "reminder_delete",
        "alarm_create", "alarm_delete", "focus_get", "focus_rule_category",
        "task_get_details", "task_completed_list", "reminder_status",
        "saved_note_add", "saved_note_search", "daily_briefing",
        "app_status", "animation_play", "app_open", "clipboard_write",
    }.issubset(names)
    assert "task_delete" in names
    assert definitions == get_tool_definitions()
    result = make_registry().execute("task_create", {"title": "Task", "unexpected": 3})
    assert result["ok"] is False
    assert result["error"] == "invalid_arguments"
    result = make_registry().execute("task_create", {"title": 42})
    assert result["error"] == "invalid_arguments"


def test_task_create_list_update_complete_reopen_and_notes():
    registry = make_registry()
    created = registry.execute("task_create", {
        "title": "Draft", "description": "First", "priority": 2,
    })
    assert created["ok"]
    task_id = created["result"]["id"]
    assert registry.execute("task_get_details", {
        "task_id": task_id,
    })["result"]["title"] == "Draft"
    assert registry.execute("task_list")["result"][0]["title"] == "Draft"

    updated = registry.execute("task_update", {
        "task_id": task_id, "title": "Final draft", "estimated_min": 30,
    })
    assert updated["result"]["title"] == "Final draft"
    noted = registry.execute("task_add_note", {"task_id": task_id, "note": "Need review"})
    assert noted["result"]["description"].startswith("First\n[")
    assert noted["result"]["description"].endswith("] Need review")
    assert registry.execute("task_complete", {"task_id": task_id})["result"]["status"] == "done"
    assert registry.execute("task_list")["result"] == []
    reopened = registry.execute("task_reopen", {"task_id": task_id})
    assert reopened["result"]["status"] == "todo"


def test_reminder_lifecycle_update_confirmation_and_delete():
    registry = make_registry()
    created = registry.execute("reminder_create", {
        "title": "Call", "due_at": time.time() + 3600,
    })
    reminder_id = created["result"]["id"]
    assert registry.execute("reminder_update", {
        "reminder_id": reminder_id, "title": "Call dentist",
    })["result"]["title"] == "Call dentist"
    assert registry.execute("reminder_snooze", {
        "reminder_id": reminder_id, "minutes": 4,
    })["result"]["status"] == "snoozed"
    assert registry.execute("reminder_dismiss", {
        "reminder_id": reminder_id,
    })["result"]["status"] == "dismissed"
    another = registry.execute("reminder_create", {
        "title": "Cancel", "due_at": time.time() + 3600, "recurrence": "interval:600",
    })["result"]["id"]
    cancelled = registry.execute("reminder_cancel", {"reminder_id": another})["result"]
    assert cancelled["enabled"] == 0
    assert cancelled["status"] == "cancelled"
    denied = registry.execute("reminder_delete", {
        "reminder_id": reminder_id, "confirmed": False,
    })
    assert denied["error"] == "confirmation_required"
    assert database.execute("SELECT 1 FROM reminders WHERE id=?", (reminder_id,)).fetchone()
    deleted = registry.execute("reminder_delete", {
        "reminder_id": reminder_id, "confirmed": True,
    })
    assert deleted["result"]["deleted"] is True
    assert not database.execute("SELECT 1 FROM reminders WHERE id=?", (reminder_id,)).fetchone()


def test_alarm_lifecycle_cancel_and_delete_confirmation():
    registry = make_registry()
    created = registry.execute("alarm_create", {
        "title": "Wake", "due_at": time.time() + 1200, "sound": False,
    })
    alarm_id = created["result"]["id"]
    updated = registry.execute("alarm_update", {
        "alarm_id": alarm_id, "title": "Early wake", "sound": True,
    })
    assert updated["result"]["title"] == "Early wake"
    assert updated["result"]["sound"] == 1
    assert registry.execute("alarm_snooze", {
        "alarm_id": alarm_id, "minutes": 3,
    })["result"]["status"] == "snoozed"
    assert registry.execute("alarm_dismiss", {
        "alarm_id": alarm_id,
    })["result"]["status"] == "dismissed"
    denied = registry.execute("alarm_delete", {"alarm_id": alarm_id})
    assert denied["error"] == "invalid_arguments"
    denied = registry.execute("alarm_delete", {
        "alarm_id": alarm_id, "confirmed": False,
    })
    assert denied["error"] == "confirmation_required"
    assert registry.execute("alarm_delete", {
        "alarm_id": alarm_id, "confirmed": True,
    })["result"]["deleted"]

    another = registry.execute("alarm_create", {
        "title": "Cancel me", "due_at": time.time() + 3600,
    })["result"]["id"]
    cancelled = registry.execute("alarm_cancel", {"alarm_id": another})["result"]
    assert cancelled["enabled"] == 0
    assert cancelled["status"] == "cancelled"


def test_focus_settings_rules_and_focus_service_operations():
    settings = Settings(focus_app_rules=[])
    focus = Focus()
    registry = make_registry(settings=settings, focus_service=focus)
    assert registry.execute("focus_get")["result"]["state"] == "IDLE"
    assert registry.execute("focus_start", {"duration_minutes": 20})["result"]["state"] == "FOCUSING"
    assert registry.execute("focus_stop")["result"]["state"] == "IDLE"

    assert registry.execute("focus_settings", {
        "focus_duration_minutes": 40,
        "focus_distraction_nudge": True,
    })["result"]["focus_duration_minutes"] == 40
    assert settings.save_count == 1
    added = registry.execute("focus_rule_add", {
        "process": "browser.exe", "category": "distracting",
    })["result"]
    rule_id = added["id"]
    assert registry.execute("focus_rule_toggle", {
        "rule_id": rule_id, "enabled": False,
    })["result"]["enabled"] is False
    assert registry.execute("focus_rule_category", {
        "rule_id": rule_id, "category": "always_allow",
    })["result"]["category"] == "always_allow"
    assert registry.execute("focus_rule_update", {
        "rule_id": rule_id, "path": r"C:\Apps\browser.exe",
    })["result"]["path"] == r"C:\Apps\browser.exe"
    assert registry.execute("focus_rule_remove", {
        "rule_id": rule_id, "confirmed": False,
    })["error"] == "confirmation_required"
    assert registry.execute("focus_rule_remove", {
        "rule_id": rule_id, "confirmed": True,
    })["result"]["removed"]
    assert registry.execute("focus_rule_list")["result"] == []


def test_saved_notes_callbacks_and_history_exclude_sensitive_arguments():
    calls = []
    registry = make_registry(
        app_status=lambda: {"state": "ready"},
        play_animation=lambda animation: calls.append(("animation", animation)) or True,
        open_application=lambda application: calls.append(("open", application)) or True,
    )
    note = registry.execute("saved_note_add", {"content": "sensitive note contents"})
    note_id = note["result"]["note_id"]
    assert registry.execute("saved_note_list")["result"][0]["content"] == "sensitive note contents"
    assert registry.execute("saved_note_search", {
        "query": "sensitive note",
    })["result"] == ["sensitive note contents"]
    assert registry.execute("saved_note_delete", {
        "note_id": note_id, "confirmed": True,
    })["result"]["deleted"]
    assert registry.execute("app_status")["result"] == {"state": "ready"}
    assert registry.execute("animation_play", {"animation": "wave"})["result"] is True
    assert registry.execute("app_open", {"application": "notepad"})["result"] is True
    assert calls == [("animation", "wave"), ("open", "notepad")]

    history = get_action_history()
    assert history
    assert all("content" not in row and "arguments" not in row for row in history)
    assert any(row["affected_item_id"] == note_id for row in history)
    assert all("sensitive note contents" not in row["result_summary"] for row in history)
    columns = {
        row["name"] for row in database.execute(
            "PRAGMA table_info(ai_tool_action_history)"
        ).fetchall()
    }
    assert "tool_name" in columns
    assert "sensitive note contents" not in str(history)
    database.close()
    database._conn = None
    persisted_history = get_action_history()
    assert len(persisted_history) == len(history)
    assert "sensitive note contents" not in str(persisted_history)


def test_clipboard_tool_validates_size_and_uses_callback():
    copied = []
    registry = make_registry(write_clipboard=lambda text: copied.append(text))

    pending = registry.execute(
        "clipboard_write",
        {"text": "Approved content", "confirmed": False},
    )
    assert pending["error"] == "confirmation_required"
    assert copied == []
    result = registry.execute(
        "clipboard_write",
        {"text": "Approved content", "confirmed": True},
    )

    assert result == {"ok": True, "result": {"characters": 16}}
    assert copied == ["Approved content"]
    too_long = registry.execute(
        "clipboard_write", {"text": "x" * 20001, "confirmed": True}
    )
    assert too_long["error"] == "invalid_arguments"
    assert copied == ["Approved content"]


def test_ids_must_exist_and_destructive_calls_never_delete_without_true():
    registry = make_registry()
    assert registry.execute("task_update", {"task_id": 999, "title": "No"})["error"] == "invalid_arguments"
    assert registry.execute("task_complete", {"task_id": 0})["error"] == "invalid_arguments"
    task = registry.execute("task_create", {"title": "Keep"})["result"]
    assert registry.execute("task_delete", {
        "task_id": task["id"], "confirmed": False,
    })["error"] == "confirmation_required"
    assert database.execute("SELECT 1 FROM tasks WHERE id=?", (task["id"],)).fetchone()
    assert registry.execute("task_delete", {
        "task_id": task["id"], "confirmed": True,
    })["result"]["deleted"]
