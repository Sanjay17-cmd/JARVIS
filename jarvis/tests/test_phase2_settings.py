"""
tests/test_phase2_settings.py — Phase 2 settings tests.

Tests:
  • panels_always_on_top default value
  • panels_always_on_top persists after save/reload
  • opacity clamps to valid range
  • All Phase 2 defaults present
  • version is 2.0.0
  • Settings migration — old file missing new keys fills defaults
"""
import json
import pytest
from pathlib import Path
from PySide6.QtWidgets import QLabel
from jarvis.config.settings import Settings
from jarvis.config.defaults import DEFAULTS
from jarvis.config.behavior_config import BehaviorConfig
from jarvis.core.command_router import CommandRouter
from jarvis.ui.settings_dialog import SettingsDialog


@pytest.fixture
def tmp_s(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    return Settings(), tmp_path


# ── Version ──────────────────────────────────────────────────────────────────

def test_version_is_2():
    from jarvis import __version__
    assert __version__ == "2.0.0"


# ── panels_always_on_top ─────────────────────────────────────────────────────

def test_panels_always_on_top_default(tmp_s):
    s, _ = tmp_s
    assert s.get("panels_always_on_top") is True


def test_panels_always_on_top_persists(tmp_s):
    s, tmp = tmp_s
    s.set("panels_always_on_top", False)
    s.save()
    s2 = Settings()
    assert s2.get("panels_always_on_top") is False


def test_panels_always_on_top_true_persists(tmp_s):
    s, _ = tmp_s
    s.set("panels_always_on_top", True)
    s.save()
    s2 = Settings()
    assert s2.get("panels_always_on_top") is True


def test_settings_has_top_section_tabs_and_persists_chat_voice_options(
    tmp_s, qtbot
):
    settings, _ = tmp_s
    dialog = SettingsDialog(settings)
    qtbot.addWidget(dialog)
    assert [
        dialog._sections.tabText(index)
        for index in range(dialog._sections.count())
    ] == [
        "General", "Notifications", "AI & Voice",
        "Built-in Responses", "Web Search", "Focus & Tools",
    ]
    dialog._tts_enabled.setChecked(True)
    dialog._ai_keyword.setText("Friday")
    dialog._ai_aliases.setText("Susanth, Computer")
    dialog._notification_category_controls["notification_reminders"].setChecked(False)
    dialog._search_provider.setCurrentIndex(
        dialog._search_provider.findData("tavily")
    )
    dialog._search_cache_ttl.setValue(120)

    legend = next(
        widget for widget in dialog.findChildren(QLabel)
        if widget.accessibleName().startswith("Chest button color legend")
    )
    assert "Purple = Voice" in legend.toolTip()

    dialog._apply()

    assert settings.get("tts_enabled") is True
    assert settings.get("ai_trigger_keyword") == "Friday"
    assert settings.get("ai_trigger_aliases") == ["Susanth", "Computer"]
    assert settings.get("notification_reminders") is False
    assert settings.get("search_provider") == "tavily"
    assert settings.get("search_cache_ttl_minutes") == 120


def test_builtin_response_settings_page_adds_and_applies_local_response(
    tmp_path, monkeypatch, qtbot
):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    settings = Settings()
    behavior = BehaviorConfig(tmp_path / "JARVIS" / "config")
    router = CommandRouter()
    router.set_responses(behavior.load("responses")["responses"])
    dialog = SettingsDialog(settings, behavior=behavior, router=router)
    qtbot.addWidget(dialog)

    dialog._response_key.setText("greeting")
    dialog._response_text.setPlainText("Hey, good to hear from you!")
    dialog._add_builtin_response()

    assert "Hey, good to hear from you!" in router._responses["greeting"]
    assert "Hey, good to hear from you!" in behavior.load("responses")[
        "responses"
    ]["greeting"]
    assert any(
        item.text() == "greeting: Hey, good to hear from you!"
        for item in (dialog._response_list.item(i)
                     for i in range(dialog._response_list.count()))
    )
    dialog.close()


def test_builtin_response_settings_page_imports_csv(
    tmp_path, monkeypatch, qtbot
):
    from PySide6.QtWidgets import QFileDialog

    monkeypatch.setenv("APPDATA", str(tmp_path))
    csv_path = tmp_path / "responses.csv"
    csv_path.write_text(
        'key,response\n'
        'greeting,"Hello, friend!"\n'
        'how_are_you,"Doing great!"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *_args, **_kwargs: (str(csv_path), "CSV files (*.csv)")),
    )
    settings = Settings()
    behavior = BehaviorConfig(tmp_path / "JARVIS" / "config")
    router = CommandRouter()
    router.set_responses(behavior.load("responses")["responses"])
    dialog = SettingsDialog(settings, behavior=behavior, router=router)
    qtbot.addWidget(dialog)

    dialog._import_builtin_responses_csv()

    assert "Hello, friend!" in router._responses["greeting"]
    assert "Doing great!" in router._responses["how_are_you"]
    dialog.close()


# ── Phase 2 defaults present ─────────────────────────────────────────────────

EXPECTED_PHASE2_KEYS = [
    "panels_always_on_top",
    "notifications_enabled",
    "notification_duration",
    "wellness_enabled",
    "wellness_hydration_enabled",
    "wellness_hydration_interval",
    "quiet_hours_enabled",
    "quiet_hour_start",
    "quiet_hour_end",
    "focus_duration_minutes",
    "tts_enabled",
    "tts_rate",
    "ai_timeout",
]

@pytest.mark.parametrize("key", EXPECTED_PHASE2_KEYS)
def test_phase2_key_in_defaults(key):
    assert key in DEFAULTS, f"Missing default for '{key}'"


# ── Opacity validation (safe clamping) ────────────────────────────────────────

def test_opacity_default_is_1(tmp_s):
    s, _ = tmp_s
    assert s.get("opacity") == pytest.approx(1.0)


def test_opacity_persists_partial(tmp_s):
    s, _ = tmp_s
    s.set("opacity", 0.55)
    s.save()
    s2 = Settings()
    assert s2.get("opacity") == pytest.approx(0.55)


# ── Migration: old file missing new keys gets defaults ───────────────────────

def test_migration_fills_missing_phase2_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    # Write a Phase-1-style settings file (no Phase 2 keys)
    settings_dir = tmp_path / "JARVIS"
    settings_dir.mkdir(parents=True)
    old_data = {"robot_size": 100, "opacity": 0.8}
    (settings_dir / "settings.json").write_text(json.dumps(old_data))

    s = Settings()
    # Phase 1 key preserved
    assert s.get("robot_size") == 100
    assert s.get("opacity") == pytest.approx(0.8)
    # Phase 2 keys filled with defaults
    assert s.get("panels_always_on_top") == DEFAULTS["panels_always_on_top"]
    assert s.get("wellness_enabled") == DEFAULTS["wellness_enabled"]


# ── Reset to defaults ─────────────────────────────────────────────────────────

def test_reset_restores_panels_always_on_top(tmp_s):
    s, _ = tmp_s
    s.set("panels_always_on_top", False)
    s.reset_to_defaults()
    assert s.get("panels_always_on_top") == DEFAULTS["panels_always_on_top"]


# ── Wellness defaults ─────────────────────────────────────────────────────────

def test_wellness_hydration_interval_default(tmp_s):
    s, _ = tmp_s
    assert s.get("wellness_hydration_interval") == 60


def test_quiet_hours_default_disabled(tmp_s):
    s, _ = tmp_s
    assert s.get("quiet_hours_enabled") is False
