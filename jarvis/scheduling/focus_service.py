"""
scheduling/focus_service.py — Part H: Pomodoro / Focus mode.

States: IDLE → FOCUSING → SHORT_BREAK → LONG_BREAK → IDLE
• Configurable durations via AdvancedConfig
• Publishes notifications via ui.notification.notify()
• Sends chest indicator updates via a callback
• Distraction nudges via a separate QTimer (optional)
"""
from __future__ import annotations

import logging
import os
import time
from enum import Enum, auto
from typing import Callable, TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer, Signal, Slot

if TYPE_CHECKING:
    from jarvis.config.settings import Settings
    from jarvis.config.advanced_config import AdvancedConfig

log = logging.getLogger(__name__)


class FocusState(Enum):
    IDLE        = auto()
    FOCUSING    = auto()
    SHORT_BREAK = auto()
    LONG_BREAK  = auto()
    PAUSED      = auto()


class FocusService(QObject):
    state_changed = Signal(str)   # FocusState.name
    tick_signal   = Signal(int)   # seconds remaining

    def __init__(self, settings: "Settings", adv: "AdvancedConfig",
                 on_indicator: Callable[[bool], None] | None = None) -> None:
        super().__init__()
        self._s           = settings
        self._adv         = adv
        self._on_indicator= on_indicator   # callback(active: bool)
        self._state       = FocusState.IDLE
        self._pomodoro    = 0   # completed focus cycles
        self._remaining   = 0  # seconds left in current phase

        self._phase_timer = QTimer(self)
        self._phase_timer.setSingleShot(True)
        self._phase_timer.timeout.connect(self._phase_done)

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._on_tick)

        self._app_watch_timer = QTimer(self)
        self._app_watch_timer.setInterval(1500)
        self._app_watch_timer.timeout.connect(self._check_foreground_app)
        self._last_app_nudge: dict[str, float] = {}

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def state(self) -> FocusState:
        return self._state

    @property
    def is_active(self) -> bool:
        return self._state != FocusState.IDLE

    def start_focus(self, duration_minutes: int | None = None) -> str:
        if self._state == FocusState.FOCUSING:
            return "⚡ Already in focus mode!"
        dur = (
            duration_minutes
            if duration_minutes is not None
            else self._s.get(
                "focus_duration_minutes",
                self._adv.get("focus_duration_minutes", 25),
            )
        )
        if not 1 <= dur <= 240:
            return "⚠ Focus duration must be between 1 and 240 minutes."
        self._enter(FocusState.FOCUSING, dur * 60)
        return f"🎯 Focus session started — {dur} minutes. You've got this!"

    def stop(self) -> str:
        if self._state == FocusState.IDLE:
            return "No focus session active."
        self._enter(FocusState.IDLE, 0)
        return "⏹ Focus session stopped."

    def pause(self) -> str:
        if self._state == FocusState.PAUSED:
            return "Focus is already paused."
        if self._state == FocusState.IDLE:
            return "No focus session active."
        self._phase_timer.stop()
        self._tick_timer.stop()
        self._app_watch_timer.stop()
        self._state = FocusState.PAUSED
        self.state_changed.emit(FocusState.PAUSED.name)
        if self._on_indicator:
            self._on_indicator(False)
        return "Focus session paused."

    def resume(self) -> str:
        if self._state != FocusState.PAUSED:
            return "Focus is not paused."
        self._enter(self._paused_state, self._remaining)
        return "Focus session resumed."

    def skip_break(self) -> str:
        if self._state in (FocusState.SHORT_BREAK, FocusState.LONG_BREAK):
            dur = self._s.get(
                "focus_duration_minutes", self._adv.get("focus_duration_minutes", 25)
            )
            self._enter(FocusState.FOCUSING, dur * 60)
            return "▶ Break skipped — back to focus!"
        return "Not in a break."

    def status(self) -> str:
        if self._state == FocusState.IDLE:
            return f"🎯 Focus mode idle. Completed {self._pomodoro} Pomodoros today."
        mins, secs = divmod(self._remaining, 60)
        phase = {
            FocusState.FOCUSING:    "🎯 Focusing",
            FocusState.SHORT_BREAK: "☕ Short break",
            FocusState.LONG_BREAK:  "🛋 Long break",
        }.get(self._state, "")
        if self._state == FocusState.PAUSED:
            phase = "⏸ Focus paused"
        return f"{phase} — {mins:02d}:{secs:02d} remaining"

    def refresh_rules(self) -> None:
        if (
            self._state == FocusState.FOCUSING
            and self._s.get("focus_distraction_nudge", False)
            and os.name == "nt"
        ):
            self._app_watch_timer.start()
        else:
            self._app_watch_timer.stop()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _enter(self, new_state: FocusState, seconds: int) -> None:
        if new_state != FocusState.PAUSED:
            self._paused_state = new_state
        self._phase_timer.stop()
        self._tick_timer.stop()
        self._state     = new_state
        self._remaining = seconds
        self.state_changed.emit(new_state.name)

        if new_state != FocusState.IDLE:
            self._phase_timer.start(seconds * 1000)
            self._tick_timer.start()
        self.refresh_rules()

        # Chest indicator: green when focusing
        if self._on_indicator:
            self._on_indicator(new_state == FocusState.FOCUSING)

        if self._s.get("notifications_enabled", True):
            from jarvis.ui.notification import notify
            if new_state == FocusState.FOCUSING:
                dur = seconds // 60
                notify("🎯", "Focus session", f"Focusing for {dur} minutes. Stay locked in!", duration_ms=5000)
            elif new_state == FocusState.SHORT_BREAK:
                dur = seconds // 60
                notify("☕", "Short break", f"Take a {dur}-minute break. Rest your eyes.", duration_ms=5000)
            elif new_state == FocusState.LONG_BREAK:
                dur = seconds // 60
                notify("🛋", "Long break", f"Great work! Take a {dur}-minute long break.", duration_ms=6000)
            elif new_state == FocusState.IDLE:
                notify("✅", "Focus ended", "Session complete. Well done!", duration_ms=4000)

        log.info("Focus state → %s (%d s)", new_state.name, seconds)

    @Slot()
    def _check_foreground_app(self) -> None:
        if self._state != FocusState.FOCUSING or not self._s.get(
            "focus_distraction_nudge", False
        ) or not self._s.get("notifications_enabled", True):
            return
        rules = [
            rule for rule in self._s.get("focus_app_rules", [])
            if rule.get("enabled", True)
        ]
        try:
            from jarvis.platform.windows_foreground import foreground_application

            active = foreground_application()
        except OSError:
            log.exception("Could not detect foreground application")
            self._app_watch_timer.stop()
            return
        if any(
            rule.get("category") == "always_allow"
            and self._rule_matches(rule, active)
            for rule in rules
        ):
            return
        matched = next(
            (
                rule for rule in rules
                if rule.get("category") == "distracting"
                and self._rule_matches(rule, active)
            ),
            None,
        )
        if matched is None:
            return
        process = active["process"]
        cooldown = int(
            self._s.get(
                "focus_nudge_cooldown_minutes",
                self._adv.get("focus_nudge_cooldown_minutes", 10),
            )
        ) * 60
        now = time.monotonic()
        if now - self._last_app_nudge.get(process, 0) < cooldown:
            return
        self._last_app_nudge[process] = now
        from jarvis.ui.notification import notify

        notify(
            "🎯",
            "Focus distraction",
            f"{active['process']} is marked distracting. Continue, pause Focus, or allow it.",
            duration_ms=15000,
            actions=[
                ("Continue anyway", lambda: None),
                ("Pause Focus", self.pause),
                ("Always allow", lambda: self._allow_app(matched)),
            ],
        )

    @staticmethod
    def _rule_matches(rule: dict, app: dict[str, str]) -> bool:
        process = str(rule.get("process", "")).casefold()
        path = str(rule.get("path", "")).casefold()
        return bool(
            process and process == app["process"]
            or path and path == app["path"].casefold()
        )

    def _allow_app(self, rule: dict) -> None:
        rules = list(self._s.get("focus_app_rules", []))
        for current in rules:
            if current.get("id") == rule.get("id"):
                current["category"] = "always_allow"
        self._s.set("focus_app_rules", rules)
        self._s.save()

    def _phase_done(self) -> None:
        if self._state == FocusState.FOCUSING:
            self._pomodoro += 1
            if self._pomodoro % 4 == 0:
                dur = self._s.get(
                    "focus_long_break_minutes",
                    self._adv.get("focus_long_break_minutes", 15),
                )
                self._enter(FocusState.LONG_BREAK, dur * 60)
            else:
                dur = self._s.get(
                    "focus_short_break_minutes",
                    self._adv.get("focus_short_break_minutes", 5),
                )
                self._enter(FocusState.SHORT_BREAK, dur * 60)
        elif self._state in (FocusState.SHORT_BREAK, FocusState.LONG_BREAK):
            dur = self._s.get(
                "focus_duration_minutes", self._adv.get("focus_duration_minutes", 25)
            )
            self._enter(FocusState.FOCUSING, dur * 60)

    def _on_tick(self) -> None:
        if self._remaining > 0:
            self._remaining -= 1
            self.tick_signal.emit(self._remaining)
