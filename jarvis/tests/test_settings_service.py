"""
tests/test_settings_service.py — Part A: settings_service unit tests.
Registry calls are mocked — no real registry writes in CI.
"""
import pytest
from unittest.mock import patch, MagicMock
from jarvis.core.settings_service import migrate, validate, set_startup, is_startup_enabled
from jarvis.config.defaults import DEFAULTS


# ── migrate() ─────────────────────────────────────────────────────────────────

def test_migrate_fills_missing_keys():
    data = {"robot_size": 100}
    result = migrate(data)
    assert "opacity" in result
    assert "wellness_enabled" in result
    assert result["robot_size"] == 100   # existing value preserved

def test_migrate_adds_schema_version():
    data = {}
    migrate(data)
    assert "schema_version" in data

def test_migrate_does_not_overwrite_existing():
    data = {"opacity": 0.5}
    migrate(data)
    assert data["opacity"] == 0.5

def test_migrate_idempotent():
    data = {}
    migrate(data)
    first = dict(data)
    migrate(data)
    assert data == first


# ── validate() ────────────────────────────────────────────────────────────────

def test_validate_clamps_opacity_low():
    data = {"opacity": 0.0}   # below min 0.1
    validate(data)
    assert data["opacity"] >= 0.1

def test_validate_clamps_opacity_high():
    data = {"opacity": 5.0}   # above max 1.0
    validate(data)
    assert data["opacity"] <= 1.0

def test_validate_clamps_fps():
    data = {"animation_fps": 999}
    validate(data)
    assert data["animation_fps"] <= 60

def test_validate_clamps_fps_low():
    data = {"animation_fps": 0}
    validate(data)
    assert data["animation_fps"] >= 5

def test_validate_clamps_robot_size():
    data = {"robot_size": 10}
    validate(data)
    assert data["robot_size"] >= 60

def test_validate_bad_type_reset_to_default():
    data = {"opacity": "bad_value"}
    validate(data)
    assert data["opacity"] == DEFAULTS["opacity"]

def test_validate_ignores_unknown_keys():
    data = {"some_future_key": "whatever"}
    validate(data)   # must not raise
    assert data["some_future_key"] == "whatever"

def test_validate_valid_values_unchanged():
    data = {"opacity": 0.8, "animation_fps": 30, "robot_size": 120}
    validate(data)
    assert data["opacity"] == pytest.approx(0.8)
    assert data["animation_fps"] == 30
    assert data["robot_size"] == 120


# ── startup registry (mocked) ─────────────────────────────────────────────────

@patch("jarvis.core.settings_service.winreg")
def test_set_startup_enabled(mock_reg):
    mock_key = MagicMock()
    mock_reg.OpenKey.return_value = mock_key
    mock_reg.HKEY_CURRENT_USER = 0
    mock_reg.KEY_SET_VALUE = 2
    mock_reg.REG_SZ = 1
    result = set_startup(True, exe_path='"python.exe" "main.py"')
    assert result is True
    mock_reg.SetValueEx.assert_called_once()

@patch("jarvis.core.settings_service.winreg")
def test_set_startup_disabled(mock_reg):
    mock_key = MagicMock()
    mock_reg.OpenKey.return_value = mock_key
    mock_reg.HKEY_CURRENT_USER = 0
    mock_reg.KEY_SET_VALUE = 2
    result = set_startup(False)
    assert result is True
    mock_reg.DeleteValue.assert_called_once()

@patch("jarvis.core.settings_service.winreg")
def test_set_startup_os_error_returns_false(mock_reg):
    mock_reg.OpenKey.side_effect = OSError("access denied")
    result = set_startup(True)
    assert result is False

@patch("jarvis.core.settings_service.winreg")
def test_is_startup_enabled_true(mock_reg):
    mock_reg.OpenKey.return_value = MagicMock()
    mock_reg.HKEY_CURRENT_USER = 0
    mock_reg.KEY_READ = 1
    mock_reg.QueryValueEx.return_value = ('"python.exe"', 1)
    assert is_startup_enabled() is True

@patch("jarvis.core.settings_service.winreg")
def test_is_startup_enabled_false(mock_reg):
    mock_reg.OpenKey.side_effect = OSError
    assert is_startup_enabled() is False


# ── Settings integration: migrate+validate called on load ─────────────────────

def test_settings_load_clamps_bad_value(tmp_path, monkeypatch):
    import json
    monkeypatch.setenv("APPDATA", str(tmp_path))
    (tmp_path / "JARVIS").mkdir()
    (tmp_path / "JARVIS" / "settings.json").write_text(
        json.dumps({"opacity": 99.0, "animation_fps": 0}), encoding="utf-8"
    )
    from jarvis.config.settings import Settings
    s = Settings()
    assert s.get("opacity") <= 1.0
    assert s.get("animation_fps") >= 5

def test_settings_load_fills_missing_phase2_keys(tmp_path, monkeypatch):
    import json
    monkeypatch.setenv("APPDATA", str(tmp_path))
    (tmp_path / "JARVIS").mkdir()
    (tmp_path / "JARVIS" / "settings.json").write_text(
        json.dumps({"robot_size": 80}), encoding="utf-8"
    )
    from jarvis.config.settings import Settings
    s = Settings()
    assert s.get("wellness_enabled") is not None
    assert s.get("panels_always_on_top") is not None
