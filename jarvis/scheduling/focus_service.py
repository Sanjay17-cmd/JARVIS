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
from enum import Enum, auto
from typing import Callable, TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer, Signal

if TYPE_CHECKING:
    from jarvis.config.settings import Settings
    from jarvis.config.advanced_config import AdvancedConfig

log = logging.getLogger(__name__)


class FocusState(Enum):
    IDLE        = auto()
    FOCUSING    = auto()
    SHORT_BREAK = auto()
    LONG_BREAK  = auto()


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

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def state(self) -> FocusState:
        return self._state

    @property
    def is_active(self) -> bool:
        return self._state != FocusState.IDLE

    def start_focus(self) -> str:
        if self._state == FocusState.FOCUSING:
            return "⚡ Already in focus mode!"
        dur = self._adv.get("focus_duration_minutes", 25)
        self._enter(FocusState.FOCUSING, dur * 60)
        return f"🎯 Focus session started — {dur} minutes. You've got this!"

    def stop(self) -> str:
        if self._state == FocusState.IDLE:
            return "No focus session active."
        self._enter(FocusState.IDLE, 0)
        return "⏹ Focus session stopped."

    def skip_break(self) -> str:
        if self._state in (FocusState.SHORT_BREAK, FocusState.LONG_BREAK):
            dur = self._adv.get("focus_duration_minutes", 25)
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
        return f"{phase} — {mins:02d}:{secs:02d} remaining"

    # ── Internal ──────────────────────────────────────────────────────────────

    def _enter(self, new_state: FocusState, seconds: int) -> None:
        self._phase_timer.stop()
        self._tick_timer.stop()
        self._state     = new_state
        self._remaining = seconds
        self.state_changed.emit(new_state.name)

        if new_state != FocusState.IDLE:
            self._phase_timer.start(seconds * 1000)
            self._tick_timer.start()

        # Chest indicator: green when focusing
        if self._on_indicator:
            self._on_indicator(new_state == FocusState.FOCUSING)

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

    def _phase_done(self) -> None:
        if self._state == FocusState.FOCUSING:
            self._pomodoro += 1
            if self._pomodoro % 4 == 0:
                dur = self._adv.get("focus_long_break_minutes", 15)
                self._enter(FocusState.LONG_BREAK, dur * 60)
            else:
                dur = self._adv.get("focus_short_break_minutes", 5)
                self._enter(FocusState.SHORT_BREAK, dur * 60)
        elif self._state in (FocusState.SHORT_BREAK, FocusState.LONG_BREAK):
            dur = self._adv.get("focus_duration_minutes", 25)
            self._enter(FocusState.FOCUSING, dur * 60)

    def _on_tick(self) -> None:
        if self._remaining > 0:
            self._remaining -= 1
            self.tick_signal.emit(self._remaining)
