"""
config/advanced_config.py — Advanced settings stored in a human-editable INI file.

File location: %APPDATA%\\JARVIS\\advanced_settings.ini
Users can edit this file in Notepad while JARVIS is closed.
Each setting has a comment describing its purpose and valid range.
reset_to_defaults() rewrites the file with factory values.
"""
from __future__ import annotations

import configparser
import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_APP_DIR_ENV = "APPDATA"
_FILE_NAME   = "advanced_settings.ini"

# ── Canonical advanced defaults with metadata ─────────────────────────────────
# Format: key -> (default, min, max, comment)
ADVANCED_SCHEMA: dict[str, tuple[Any, Any, Any, str]] = {
    # [animation]
    "animation_fps":          (30,   5,    60,   "Frames per second for robot animation (5–60)"),
    # [movement]
    "movement_speed":         (1.2,  0.1,  10.0, "Robot movement speed in px per frame (0.1–10.0)"),
    "safe_margin":            (20,   0,    200,  "Minimum pixels from screen edge (0–200)"),
    "start_x":                (-1,   -1,   7680, "Initial X position (-1 = auto)"),
    "start_y":                (-1,   -1,   4320, "Initial Y position (-1 = auto)"),
    # [notifications]
    "notification_duration":  (5,    1,    30,   "Desktop notification display time in seconds (1–30)"),
    # [wellness]
    "wellness_hydration_interval": (60,  10, 480, "Water reminder interval in minutes (10–480)"),
    "wellness_stretch_interval":   (60,  10, 480, "Stretch reminder interval in minutes (10–480)"),
    "wellness_eyerest_interval":   (20,   5, 120, "Eye-rest (20-20-20) interval in minutes (5–120)"),
    "wellness_active_hour_start":  (8,    0,  23, "Wellness reminders start hour, 24h (0–23)"),
    "wellness_active_hour_end":    (22,   0,  23, "Wellness reminders end hour, 24h (0–23)"),
    # [quiet_hours]
    "quiet_hour_start":       (22,   0,   23,   "Quiet hours begin, 24h clock (0–23)"),
    "quiet_hour_end":         (8,    0,   23,   "Quiet hours end, 24h clock (0–23)"),
    # [focus]
    "focus_duration_minutes":      (25,  1,  240, "Default focus session length in minutes (1–240)"),
    "focus_short_break_minutes":   (5,   1,   60, "Pomodoro short break in minutes (1–60)"),
    "focus_long_break_minutes":    (15,  5,  120, "Pomodoro long break in minutes (5–120)"),
    "focus_nudge_cooldown_minutes":(10,  1,   60, "Min minutes between distraction nudges (1–60)"),
    # [voice]
    "tts_rate":               (175,  50,  400,  "TTS speech rate in words per minute (50–400)"),
    "tts_volume":             (0.9,  0.0, 1.0,  "TTS volume 0.0–1.0"),
    # [ai]
    "ai_timeout":             (30,   5,   300,  "AI provider request timeout in seconds (5–300)"),
    # [system]
    "log_level":              ("INFO", None, None, "Log verbosity: DEBUG, INFO, WARNING, ERROR"),
    "camera_index":           (0,    0,    9,    "Camera device index (0 = default)"),
}

_SECTIONS = {
    "animation":    ["animation_fps"],
    "movement":     ["movement_speed", "safe_margin", "start_x", "start_y"],
    "notifications":["notification_duration"],
    "wellness":     ["wellness_hydration_interval", "wellness_stretch_interval",
                     "wellness_eyerest_interval", "wellness_active_hour_start",
                     "wellness_active_hour_end"],
    "quiet_hours":  ["quiet_hour_start", "quiet_hour_end"],
    "focus":        ["focus_duration_minutes", "focus_short_break_minutes",
                     "focus_long_break_minutes", "focus_nudge_cooldown_minutes"],
    "voice":        ["tts_rate", "tts_volume"],
    "ai":           ["ai_timeout"],
    "system":       ["log_level", "camera_index"],
}


def _adv_path() -> Path:
    base = os.environ.get(_APP_DIR_ENV) or str(Path.home() / "AppData" / "Roaming")
    d = Path(base) / "JARVIS"
    d.mkdir(parents=True, exist_ok=True)
    return d / _FILE_NAME


def _write_ini(data: dict[str, Any], path: Path) -> None:
    lines = [
        "# JARVIS Advanced Configuration",
        "# Edit this file to customise advanced behaviour.",
        "# Values outside the valid range shown in comments are clamped automatically.",
        "# To reset everything to factory defaults, delete this file or click",
        "# 'Reset Defaults' in Settings — the file will be regenerated.",
        "",
    ]
    for section, keys in _SECTIONS.items():
        lines.append(f"[{section}]")
        for k in keys:
            if k not in ADVANCED_SCHEMA:
                continue
            _, lo, hi, comment = ADVANCED_SCHEMA[k]
            lines.append(f"# {comment}")
            lines.append(f"{k} = {data.get(k, ADVANCED_SCHEMA[k][0])}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _clamp(key: str, value: Any) -> Any:
    schema = ADVANCED_SCHEMA.get(key)
    if not schema:
        return value
    _, lo, hi, _ = schema
    if lo is None and hi is None:
        return value
    try:
        typ = type(schema[0])
        v = typ(value)
        if lo is not None: v = max(typ(lo), v)
        if hi is not None: v = min(typ(hi), v)
        return v
    except (TypeError, ValueError):
        return schema[0]


class AdvancedConfig:
    """Reads/writes the advanced INI file. Falls back to defaults on error."""

    def __init__(self) -> None:
        self._path = _adv_path()
        self._data: dict[str, Any] = {k: v[0] for k, v in ADVANCED_SCHEMA.items()}
        self.load()

    def load(self) -> None:
        if not self._path.exists():
            self.reset_to_defaults()
            return
        try:
            cp = configparser.ConfigParser()
            cp.read(str(self._path), encoding="utf-8")
            for section in cp.sections():
                for key, raw in cp.items(section):
                    if key in ADVANCED_SCHEMA:
                        default = ADVANCED_SCHEMA[key][0]
                        try:
                            typed = type(default)(raw)
                        except (TypeError, ValueError):
                            typed = default
                        self._data[key] = _clamp(key, typed)
        except Exception as exc:
            log.warning("Could not read advanced config: %s — using defaults", exc)

    def save(self) -> None:
        try:
            _write_ini(self._data, self._path)
        except Exception as exc:
            log.error("Could not save advanced config: %s", exc)

    def reset_to_defaults(self) -> None:
        self._data = {k: v[0] for k, v in ADVANCED_SCHEMA.items()}
        self.save()
        log.info("Advanced config reset to defaults.")

    def get(self, key: str, fallback: Any = None) -> Any:
        return self._data.get(key, fallback)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = _clamp(key, value)

    @property
    def path(self) -> str:
        return str(self._path)
