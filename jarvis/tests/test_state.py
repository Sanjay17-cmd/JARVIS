"""
tests/test_state.py — Unit tests for the StateManager.
No Qt required.
"""
import pytest
from jarvis.core.state import StateManager, RobotState


def test_initial_state():
    sm = StateManager()
    assert sm.state is RobotState.IDLE


def test_valid_transition_idle_to_thinking():
    sm = StateManager()
    result = sm.transition(RobotState.THINKING)
    assert result is True
    assert sm.state is RobotState.THINKING


def test_invalid_transition_blocked():
    sm = StateManager()
    # IDLE → SPEAKING is not allowed
    result = sm.transition(RobotState.SPEAKING)
    assert result is False
    assert sm.state is RobotState.IDLE   # unchanged


def test_full_command_cycle():
    sm = StateManager()
    assert sm.transition(RobotState.THINKING)
    assert sm.transition(RobotState.SUCCESS)
    assert sm.transition(RobotState.IDLE)
    assert sm.state is RobotState.IDLE


def test_pause_and_resume():
    sm = StateManager()
    sm.transition(RobotState.THINKING)
    sm.pause()
    assert sm.state is RobotState.PAUSED
    assert sm.is_paused()
    sm.resume()
    assert sm.state is RobotState.THINKING
    assert not sm.is_paused()


def test_listener_called_on_transition():
    sm = StateManager()
    events: list[tuple] = []
    sm.add_listener(lambda old, new: events.append((old, new)))
    sm.transition(RobotState.THINKING)
    assert len(events) == 1
    assert events[0] == (RobotState.IDLE, RobotState.THINKING)


def test_force_transition_bypasses_guard():
    sm = StateManager()
    # IDLE → SPEAKING normally blocked
    sm.force_transition(RobotState.SPEAKING)
    assert sm.state is RobotState.SPEAKING


def test_all_states_reachable():
    """Ensure every RobotState can be reached via force_transition."""
    sm = StateManager()
    for state in RobotState:
        sm.force_transition(state)
        assert sm.state is state


def test_listener_not_duplicated():
    sm = StateManager()
    count = [0]
    def listener(old, new): count[0] += 1
    sm.add_listener(listener)
    sm.add_listener(listener)   # second registration ignored
    sm.transition(RobotState.THINKING)
    assert count[0] == 1
