"""
core/event_bus.py — Lightweight typed publish/subscribe event bus.

UI, voice, vision and action modules communicate exclusively through
this bus so no module imports another module's concrete classes.

Usage:
    bus = EventBus()
    bus.subscribe("state_changed", my_handler)
    bus.publish("state_changed", old=IDLE, new=LISTENING)
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Callable

log = logging.getLogger(__name__)

Handler = Callable[..., None]


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, event: str, handler: Handler) -> None:
        if handler not in self._subs[event]:
            self._subs[event].append(handler)
            log.debug("Subscribed %s to '%s'", handler.__qualname__, event)

    def unsubscribe(self, event: str, handler: Handler) -> None:
        try:
            self._subs[event].remove(handler)
        except ValueError:
            pass

    def publish(self, event: str, **kwargs: Any) -> None:
        log.debug("Event '%s' published: %s", event, kwargs)
        for handler in list(self._subs.get(event, [])):
            try:
                handler(**kwargs)
            except Exception:
                log.exception("Handler %s raised on event '%s'", handler, event)

    def clear(self) -> None:
        self._subs.clear()
