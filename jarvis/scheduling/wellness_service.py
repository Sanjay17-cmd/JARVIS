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
import time
from datetime import datetime
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject

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

    def start(self) -> None:
        from jarvis.scheduling import database as db
        from jarvis.scheduling.reminder_service import add_reminder

        enabled = self._s.get("wellness_enabled", True)
        for item in _WELLNESS_ITEMS:
            source_key = f"wellness:{item['key']}"
            should_enable = enabled and self._s.get(item["enabled_key"], True)
            row = db.execute(
                "SELECT * FROM reminders WHERE source_key=?", (source_key,)
            ).fetchone()
            if not should_enable:
                if row:
                    db.execute(
                        "UPDATE reminders SET enabled=0,status='dismissed' "
                        "WHERE source_key=? AND completed=0",
                        (source_key,),
                    )
                continue
            interval_seconds = int(
                self._s.get(
                    f"wellness_{item['key']}_interval_seconds",
                    int(self._adv.get(item["adv_key"], item["default"]) * 60),
                )
            )
            if interval_seconds <= 0:
                interval_seconds = int(self._adv.get(item["adv_key"], item["default"]) * 60)
            if row is None:
                add_reminder(
                    item["title"],
                    time.time() + interval_seconds,
                    item["body"],
                    recurrence=f"interval:{interval_seconds}",
                    source_key=source_key,
                )
            else:
                reset_schedule = (
                    row["recurrence"] != f"interval:{interval_seconds}"
                    or not row["enabled"]
                    or row["completed"]
                )
                db.execute(
                    "UPDATE reminders SET title=?,description=?,recurrence=?,"
                    "enabled=1,completed=0,status='scheduled',"
                    "due_at=CASE WHEN ? THEN ? ELSE due_at END,"
                    "notified=CASE WHEN ? THEN 0 ELSE notified END "
                    "WHERE source_key=?",
                    (
                        item["title"], item["body"], f"interval:{interval_seconds}",
                        int(reset_schedule), time.time() + interval_seconds,
                        int(reset_schedule), source_key,
                    ),
                )
        db.commit()
        log.info("Persistent wellness reminders synchronized.")

    def stop(self) -> None:
        # Pending reminders remain in SQLite and are reconstructed on next launch.
        return

    def refresh(self) -> None:
        """Reconcile persisted wellness schedules with the current settings."""
        self.start()

    def can_deliver(self) -> bool:
        return (
            self._s.get("wellness_enabled", True)
            and self._s.get("notifications_enabled", True)
            and not _in_quiet_hours(self._s)
            and _in_active_hours(self._adv)
        )
