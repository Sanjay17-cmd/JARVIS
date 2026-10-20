from jarvis.scheduling.focus_service import FocusService
from jarvis.scheduling.wellness_service import WellnessService


class _Settings:
    def __init__(self, values):
        self._values = values

    def get(self, key, default=None):
        return self._values.get(key, default)


class _Advanced:
    def get(self, key, default=None):
        return {
            "wellness_hydration_interval": 60,
            "wellness_stretch_interval": 60,
            "wellness_eyerest_interval": 20,
            "focus_duration_minutes": 25,
            "focus_nudge_cooldown_minutes": 10,
        }.get(key, default)


def test_wellness_persists_only_enabled_reminder_types(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from jarvis.scheduling import database
    database._conn = None
    settings = _Settings({
        "wellness_enabled": True,
        "wellness_hydration_enabled": True,
        "wellness_stretch_enabled": False,
        "wellness_eyerest_enabled": False,
    })
    service = WellnessService(settings, _Advanced())
    service.start()
    try:
        rows = database.execute(
            "SELECT source_key,recurrence FROM reminders"
        ).fetchall()
        assert [(row["source_key"], row["recurrence"]) for row in rows] == [
            ("wellness:hydration", "interval:3600")
        ]
        first_due = database.execute(
            "SELECT due_at FROM reminders WHERE source_key='wellness:hydration'"
        ).fetchone()["due_at"]
        service.refresh()
        assert database.execute(
            "SELECT COUNT(*) FROM reminders WHERE source_key='wellness:hydration'"
        ).fetchone()[0] == 1
        assert database.execute(
            "SELECT due_at FROM reminders WHERE source_key='wellness:hydration'"
        ).fetchone()["due_at"] == first_due
    finally:
        service.stop()
        database.close()


def test_focus_duration_is_bounded(qtbot):
    service = FocusService(_Settings({}), _Advanced())
    assert "between 1 and 240" in service.start_focus(0)
    assert "between 1 and 240" in service.start_focus(241)
    assert not service.is_active


def test_focus_rule_matching_uses_process_or_exact_path():
    rule = {
        "process": "browser.exe",
        "path": r"C:\Apps\Browser\browser.exe",
    }
    assert FocusService._rule_matches(
        rule,
        {"process": "browser.exe", "path": r"D:\Other\browser.exe", "pid": "12"},
    )
    assert FocusService._rule_matches(
        rule,
        {"process": "other.exe", "path": r"C:\Apps\Browser\browser.exe", "pid": "12"},
    )
    assert not FocusService._rule_matches(
        rule,
        {"process": "other.exe", "path": r"D:\Other\app.exe", "pid": "12"},
    )
