"""
core/settings_service.py — Startup registry + settings migration helpers.

Part A requirements:
  • launch_on_startup → HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run
  • migrate() — fills missing keys from DEFAULTS, bumps schema_version
  • validate() — clamps values to VALIDATORS ranges
"""
from __future__ import annotations

import logging
import winreg
from pathlib import Path
from typing import Any

from jarvis.config.defaults import DEFAULTS, VALIDATORS

log = logging.getLogger(__name__)
_APP_NAME = "JARVIS"
_RUN_KEY  = r"Software\Microsoft\Windows\CurrentVersion\Run"


# ── Startup registry ──────────────────────────────────────────────────────────

def set_startup(enabled: bool, exe_path: str = "") -> bool:
    """
    Add or remove JARVIS from Windows startup (HKCU Run).
    Returns True on success.
    exe_path defaults to the current Python interpreter + main.py.
    """
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE
        )
        if enabled:
            if not exe_path:
                import sys
                main = Path(sys.argv[0]).resolve()
                exe_path = f'"{sys.executable}" "{main}"'
            winreg.SetValueEx(key, _APP_NAME, 0, winreg.REG_SZ, exe_path)
            log.info("Startup entry added: %s", exe_path)
        else:
            try:
                winreg.DeleteValue(key, _APP_NAME)
                log.info("Startup entry removed.")
            except FileNotFoundError:
                pass   # already absent
        winreg.CloseKey(key)
        return True
    except OSError as exc:
        log.warning("Could not modify startup registry: %s", exc)
        return False


def is_startup_enabled() -> bool:
    """Return True if JARVIS is registered in HKCU Run."""
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_READ
        )
        winreg.QueryValueEx(key, _APP_NAME)
        winreg.CloseKey(key)
        return True
    except (OSError, FileNotFoundError):
        return False


# ── Settings migration ────────────────────────────────────────────────────────

_SCHEMA_VERSION = 3   # increment when DEFAULTS changes shape


def migrate(data: dict[str, Any]) -> dict[str, Any]:
    """
    Fill any keys missing from *data* using DEFAULTS.
    Bumps schema_version.  Never removes existing user values.
    """
    changed = False
    for key, default in DEFAULTS.items():
        if key not in data:
            data[key] = default
            changed = True
    if data.get("schema_version") != _SCHEMA_VERSION:
        data["schema_version"] = _SCHEMA_VERSION
        changed = True
    if changed:
        log.debug("Settings migrated to schema v%d", _SCHEMA_VERSION)
    return data


# ── Validation ────────────────────────────────────────────────────────────────

def validate(data: dict[str, Any]) -> dict[str, Any]:
    """
    Clamp numeric settings to their allowed ranges.
    Invalid types are replaced with the default value.
    """
    for key, (typ, lo, hi) in VALIDATORS.items():
        if key not in data:
            continue
        try:
            v = typ(data[key])
            if lo is not None:
                v = max(typ(lo), v)
            if hi is not None:
                v = min(typ(hi), v)
            data[key] = v
        except (TypeError, ValueError):
            data[key] = DEFAULTS.get(key)
            log.warning("Invalid value for '%s', reset to default.", key)
    return data
