"""
core/state.py — Centralised state machine for JARVIS.

States:
    IDLE        — Default resting state.
    LISTENING   — Microphone active, waiting for speech.
    THINKING    — Processing command / waiting for AI response.
    SPEAKING    — TTS output active.
    SUCCESS     — Command completed successfully.
    ERROR       — Something went wrong.
    PAUSED      — All activity paused by the user.
"""
from __future__ import annotations

import logging
from enum import Enum, auto
from typing import Callable

log = logging.getLogger(__name__)


class RobotState(Enum):
    IDLE = auto()
    LISTENING = auto()
    THINKING = auto()
    SPEAKING = auto()
    SUCCESS = auto()
    ERROR = auto()
    PAUSED = auto()


# Valid transitions: state → allowed next states
_TRANSITIONS: dict[RobotState, set[RobotState]] = {
    RobotState.IDLE:      {RobotState.LISTENING, RobotState.THINKING, RobotState.PAUSED, RobotState.ERROR},
    RobotState.LISTENING: {RobotState.THINKING, RobotState.IDLE, RobotState.PAUSED, RobotState.ERROR},
    RobotState.THINKING:  {RobotState.SPEAKING, RobotState.SUCCESS, RobotState.ERROR, RobotState.IDLE},
    RobotState.SPEAKING:  {RobotState.IDLE, RobotState.SUCCESS, RobotState.ERROR},
    RobotState.SUCCESS:   {RobotState.IDLE, RobotState.PAUSED},
    RobotState.ERROR:     {RobotState.IDLE, RobotState.PAUSED},
    RobotState.PAUSED:    {RobotState.IDLE},
}

StateChangeCallback = Callable[[RobotState, RobotState], None]


class StateManager:
    """
    Thread-safe state machine.  Listeners registered via
    ``add_listener`` are called synchronously on the calling thread;
    in production, callers should emit a Qt signal from the UI layer
    rather than touching widgets directly from worker threads.
    """

    def __init__(self, initial: RobotState = RobotState.IDLE) -> None:
        self._state = initial
        self._listeners: list[StateChangeCallback] = []
        self._pre_pause_state: RobotState = RobotState.IDLE

    # ── query ────────────────────────────────────────────────────

    @property
    def state(self) -> RobotState:
        return self._state

    def is_paused(self) -> bool:
        return self._state is RobotState.PAUSED

    # ── mutation ─────────────────────────────────────────────────

    def transition(self, new_state: RobotState) -> bool:
        """
        Attempt to move to *new_state*.  Returns True on success,
        False if the transition is not allowed.
        """
        allowed = _TRANSITIONS.get(self._state, set())
        if new_state not in allowed:
            log.warning(
                "Invalid transition %s → %s (allowed: %s)",
                self._state.name,
                new_state.name,
                {s.name for s in allowed},
            )
            return False

        old = self._state
        self._state = new_state
        log.debug("State %s → %s", old.name, new_state.name)
        for cb in list(self._listeners):
            try:
                cb(old, new_state)
            except Exception:
                log.exception("State listener raised an exception")
        return True

    def force_transition(self, new_state: RobotState) -> None:
        """Bypass guard-rails — use only for init or error recovery."""
        old = self._state
        self._state = new_state
        log.debug("Forced state %s → %s", old.name, new_state.name)
        for cb in list(self._listeners):
            try:
                cb(old, new_state)
            except Exception:
                log.exception("State listener raised an exception")

    def pause(self) -> None:
        if self._state is not RobotState.PAUSED:
            self._pre_pause_state = self._state
            self.force_transition(RobotState.PAUSED)

    def resume(self) -> None:
        if self._state is RobotState.PAUSED:
            self.force_transition(self._pre_pause_state)

    # ── listeners ────────────────────────────────────────────────

    def add_listener(self, cb: StateChangeCallback) -> None:
        if cb not in self._listeners:
            self._listeners.append(cb)

    def remove_listener(self, cb: StateChangeCallback) -> None:
        self._listeners.discard(cb) if hasattr(self._listeners, 'discard') else None
        try:
            self._listeners.remove(cb)
        except ValueError:
            pass
