"""
tests/test_settings.py — Unit tests for Settings persistence.
"""
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from jarvis.config.settings import Settings
from jarvis.config.defaults import DEFAULTS


@pytest.fixture
def tmp_settings(tmp_path, monkeypatch):
    """Redirect APPDATA to a temp dir so tests don't pollute real settings."""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    s = Settings()
    return s, tmp_path


def test_defaults_loaded(tmp_settings):
    s, _ = tmp_settings
    assert s.get("robot_size") == DEFAULTS["robot_size"]
    assert s.get("auto_movement") == DEFAULTS["auto_movement"]


def test_set_and_get(tmp_settings):
    s, _ = tmp_settings
    s.set("robot_size", 200)
    assert s.get("robot_size") == 200


def test_persist_to_disk(tmp_settings):
    s, tmp = tmp_settings
    s.set("robot_size", 180)
    s.save()

    settings_file = tmp / "JARVIS" / "settings.json"
    assert settings_file.exists()
    data = json.loads(settings_file.read_text())
    assert data["robot_size"] == 180


def test_load_from_disk(tmp_settings):
    s, tmp = tmp_settings
    s.set("opacity", 0.75)
    s.save()

    # Create a fresh Settings object pointing to same dir
    s2 = Settings()
    assert s2.get("opacity") == pytest.approx(0.75)


def test_missing_keys_filled_by_defaults(tmp_settings):
    s, tmp = tmp_settings
    # Write a partial settings file
    settings_file = tmp / "JARVIS" / "settings.json"
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(json.dumps({"robot_size": 90}))

    s2 = Settings()
    assert s2.get("robot_size") == 90
    assert s2.get("animation_fps") == DEFAULTS["animation_fps"]   # filled


def test_legacy_default_chest_colors_migrate_but_custom_colors_remain(
    tmp_settings,
):
    _settings, tmp = tmp_settings
    settings_file = tmp / "JARVIS" / "settings.json"
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(json.dumps({
        "chest_buttons": [
            {"id": 0, "color": "#00dcff"},
            {"id": 1, "color": "#123456"},
        ],
    }))

    migrated = Settings()

    assert migrated.get("chest_buttons")[0]["color"] == "#B84DFF"
    assert migrated.get("chest_buttons")[1]["color"] == "#123456"


def test_legacy_gemini_provider_and_model_migrate_to_gateway_settings(tmp_settings):
    _settings, tmp = tmp_settings
    settings_file = tmp / "JARVIS" / "settings.json"
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(json.dumps({
        "ai_provider": "gemini",
        "ai_model": "gemini-account-model",
    }))

    migrated = Settings()

    assert migrated.get("ai_primary_provider") == "gemini"
    assert migrated.get("ai_primary_model") == "gemini-account-model"


def test_legacy_openai_provider_and_model_remain_supported_by_gateway(tmp_settings):
    _settings, tmp = tmp_settings
    settings_file = tmp / "JARVIS" / "settings.json"
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(json.dumps({
        "ai_provider": "openai",
        "ai_model": "gpt-legacy-model",
        "ai_api_key_env_var": "OPENAI_API_KEY",
    }))

    migrated = Settings()

    assert migrated.get("ai_primary_provider") == "openai"
    assert migrated.get("ai_primary_model") == "gpt-legacy-model"


def test_reset_to_defaults(tmp_settings):
    s, _ = tmp_settings
    s.set("robot_size", 999)
    s.reset_to_defaults()
    assert s.get("robot_size") == DEFAULTS["robot_size"]


def test_dict_subscript_access(tmp_settings):
    s, _ = tmp_settings
    s["opacity"] = 0.5
    assert s["opacity"] == pytest.approx(0.5)


def test_as_dict_is_copy(tmp_settings):
    s, _ = tmp_settings
    d = s.as_dict()
    d["robot_size"] = 9999
    assert s.get("robot_size") != 9999  # original unchanged
