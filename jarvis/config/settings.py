"""
config/settings.py — Persistent JSON settings manager.
Saves to %APPDATA%/JARVIS/settings.json (user-writable, never
inside the installation directory).
"""
from __future__ import annotations

import json
import logging
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

from .defaults import DEFAULTS

log = logging.getLogger(__name__)


def _app_data_dir() -> Path:
    base = os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming"
    p = Path(base) / "JARVIS"
    p.mkdir(parents=True, exist_ok=True)
    return p


class Settings:
    """
    Thin wrapper around a JSON file that merges stored values with
    DEFAULTS so new keys are always available after an upgrade.
    """

    def __init__(self) -> None:
        self._path = _app_data_dir() / "settings.json"
        self._data: dict[str, Any] = deepcopy(DEFAULTS)
        self.load()

    # ── public API ──────────────────────────────────────────────

    def load(self) -> None:
        if self._path.exists():
            try:
                stored = json.loads(self._path.read_text(encoding="utf-8"))
                self._data.update(stored)
                log.info("Settings loaded from %s", self._path)
            except Exception as exc:
                log.warning("Could not load settings (%s); using defaults.", exc)
        # Migrate missing keys + clamp out-of-range values
        try:
            from jarvis.core.settings_service import migrate, validate
            migrate(self._data)
            validate(self._data)
        except Exception:
            pass  # never let migration crash the app

    def save(self) -> None:
        try:
            self._path.write_text(
                json.dumps(self._data, indent=2), encoding="utf-8"
            )
            log.info("Settings saved to %s", self._path)
        except Exception as exc:
            log.error("Could not save settings: %s", exc)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def reset_to_defaults(self) -> None:
        self._data = deepcopy(DEFAULTS)

    def as_dict(self) -> dict[str, Any]:
        return deepcopy(self._data)

    # ── convenience properties ───────────────────────────────────

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._data[key] = value
