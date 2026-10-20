"""
ai/__init__.py — AI provider interface stub.
Concrete providers (OpenAI, Anthropic, local) planned for Phase 4.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
import logging
log = logging.getLogger(__name__)


class AIProvider(ABC):
    """Abstract interface — never hardcode API keys."""

    @abstractmethod
    def complete(self, prompt: str) -> str: ...

    @abstractmethod
    def stream(self, prompt: str):
        """Yield response chunks for streaming display."""
        ...


class NullProvider(AIProvider):
    """Default no-op provider active until a real one is configured."""

    def complete(self, prompt: str) -> str:
        return (
            "🤖 No AI provider configured. "
            "Set ai_provider in Settings (Phase 4) to enable AI responses."
        )

    def stream(self, prompt: str):
        yield self.complete(prompt)
