"""
scheduling/wellness_service.py — Part F: Wellness reminder engine.

Reminders: hydration (drink water), stretch, eye-rest (20-20-20 rule).
• Intervals read from AdvancedConfig (can be changed without restart via the INI)
• Respects quiet hours from settings
• Publishes notifications via ui.notification.notify()
• All timers run on the Qt GUI thread via QTimer — no threads needed
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer, QObject, Slot

if TYPE_CHECKING:
    from jarvis.config.settings import Settings
    from jarvis.config.advanced_config import AdvancedConfig

log = logging.getLogger(__name__)

_WELLNESS_ITEMS = [
    {
        "key":      "hydration",
        "enabled_key": "wellness_hydration_enabled",
        "adv_key":  "wellness_hydration_interval",
        "icon":     "💧",
        "title":    "Hydration reminder",
        "body":     "Time to drink some water! Stay hydrated.",
        "default":  60,
    },
    {
        "key":      "stretch",
        "enabled_key": "wellness_stretch_enabled",
        "adv_key":  "wellness_stretch_interval",
        "icon":     "🧘",
        "title":    "Stretch break",
        "body":     "Stand up and stretch for 2 minutes. Your body will thank you.",
        "default":  60,
    },
    {
        "key":      "eyerest",
        "enabled_key": "wellness_eyerest_enabled",
        "adv_key":  "wellness_eyerest_interval",
        "icon":     "👁",
        "title":    "Eye rest — 20-20-20",
        "body":     "Look at something 20 feet away for 20 seconds.",
        "default":  20,
    },
]


def _in_quiet_hours(settings: "Settings") -> bool:
    if not settings.get("quiet_hours_enabled", False):
        return False
    now_h = datetime.now().hour
    qs = settings.get("quiet_hour_start", 22)
    qe = settings.get("quiet_hour_end",   8)
    if qs <= qe:
        return qs <= now_h < qe
    return now_h >= qs or now_h < qe   # overnight range


def _in_active_hours(adv: "AdvancedConfig") -> bool:
    h = datetime.now().hour
    return adv.get("wellness_active_hour_start", 8) <= h < adv.get("wellness_active_hour_end", 22)


class WellnessService(QObject):
    """Manages all wellness timers. Instantiate once, call start()."""

    def __init__(self, settings: "Settings", adv: "AdvancedConfig") -> None:
        super().__init__()
        self._s   = settings
        self._adv = adv
        self._timers: dict[str, QTimer] = {}

    def start(self) -> None:
        if not self._s.get("wellness_enabled", True):
            log.info("Wellness reminders disabled.")
            return
        for item in _WELLNESS_ITEMS:
            if self._s.get(item["enabled_key"], True):
                self._create_timer(item)
        log.info("Wellness service started (%d timers).", len(self._timers))

    def stop(self) -> None:
        for t in self._timers.values():
            t.stop()
        self._timers.clear()

    def refresh(self) -> None:
        """Call after settings change to restart timers with new intervals."""
        self.stop()
        self.start()

    def _create_timer(self, item: dict) -> None:
        interval_min = self._adv.get(item["adv_key"], item["default"])
        t = QTimer(self)
        t.setInterval(int(interval_min * 60 * 1000))
        t.timeout.connect(lambda i=item: self._fire(i))
        t.start()
        self._timers[item["key"]] = t
        log.debug("Wellness timer '%s' every %d min", item["key"], interval_min)

    def _fire(self, item: dict) -> None:
        if not self._s.get("wellness_enabled", True):
            return
        if _in_quiet_hours(self._s) or not _in_active_hours(self._adv):
            log.debug("Wellness '%s' skipped (quiet/inactive hours)", item["key"])
            return
        from jarvis.ui.notification import notify
        notify(item["icon"], item["title"], item["body"], duration_ms=8000)
        log.info("Wellness: %s", item["title"])
