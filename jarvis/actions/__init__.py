"""
actions/__init__.py — Safe action registry.
Only explicitly registered, reviewed actions can be executed.
AI output must never directly invoke shell commands.
"""
from __future__ import annotations
from typing import Callable, Any
import logging
log = logging.getLogger(__name__)

ActionFn = Callable[..., Any]


class ActionRegistry:
    def __init__(self) -> None:
        self._actions: dict[str, ActionFn] = {}

    def register(self, name: str, fn: ActionFn, requires_confirm: bool = False) -> None:
        self._actions[name] = fn
        log.debug("Action registered: '%s' (confirm=%s)", name, requires_confirm)

    def execute(self, name: str, **kwargs: Any) -> Any:
        fn = self._actions.get(name)
        if fn is None:
            raise KeyError(f"No action registered for '{name}'")
        return fn(**kwargs)

    def list_actions(self) -> list[str]:
        return list(self._actions.keys())
