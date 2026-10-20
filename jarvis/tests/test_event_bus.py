"""
tests/test_event_bus.py — Unit tests for the EventBus.
"""
import pytest
from jarvis.core.event_bus import EventBus


def test_publish_subscribe():
    bus = EventBus()
    received = []
    bus.subscribe("test_event", lambda **kw: received.append(kw))
    bus.publish("test_event", value=42)
    assert received == [{"value": 42}]


def test_no_subscribers_no_error():
    bus = EventBus()
    bus.publish("ghost_event", x=1)  # should not raise


def test_multiple_subscribers():
    bus = EventBus()
    results = []
    bus.subscribe("ev", lambda **kw: results.append(1))
    bus.subscribe("ev", lambda **kw: results.append(2))
    bus.publish("ev")
    assert sorted(results) == [1, 2]


def test_unsubscribe():
    bus = EventBus()
    results = []
    def handler(**kw): results.append(kw)
    bus.subscribe("ev", handler)
    bus.unsubscribe("ev", handler)
    bus.publish("ev")
    assert results == []


def test_handler_exception_does_not_break_others():
    bus = EventBus()
    results = []
    bus.subscribe("ev", lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    bus.subscribe("ev", lambda **kw: results.append("ok"))
    bus.publish("ev")   # should not raise
    assert "ok" in results


def test_duplicate_subscription_ignored():
    bus = EventBus()
    count = [0]
    def handler(**kw): count[0] += 1
    bus.subscribe("ev", handler)
    bus.subscribe("ev", handler)
    bus.publish("ev")
    assert count[0] == 1
