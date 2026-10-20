"""
ai/provider.py — Part J: AI provider abstraction.

Supports:
  • EchoProvider (always available, no API key needed — fallback/dev mode)
  • OpenAIProvider (gpt-4o-mini / gpt-3.5-turbo — needs OPENAI_API_KEY env var)

The active provider is chosen from settings["ai_provider"]:
  "echo"   → EchoProvider (default, works offline)
  "openai" → OpenAIProvider

Usage:
  router.register_ai_fallback(get_provider(settings).ask)
"""
from __future__ import annotations

import logging
import os
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from jarvis.config.settings import Settings

log = logging.getLogger(__name__)


# ── Abstract base ──────────────────────────────────────────────────────────────

class AIProvider(ABC):
    @abstractmethod
    def ask(self, text: str) -> str: ...

    @property
    @abstractmethod
    def name(self) -> str: ...


# ── Echo (offline fallback) ───────────────────────────────────────────────────

class EchoProvider(AIProvider):
    """Simple rule-based responder. Always works, no dependencies."""

    _RESPONSES = {
        "who are you":    "I'm JARVIS, your AI desktop companion! 🤖",
        "how are you":    "Running at full power! All systems nominal. ⚡",
        "what can you do":"I can open apps, set reminders, manage tasks, run focus sessions, and more! Type 'help' for commands.",
        "thank you":      "You're welcome! Always here to help. 😊",
        "thanks":         "Anytime! 👍",
        "bye":            "Goodbye! JARVIS will be here when you need me.",
        "hi":             "Hello! How can I help you today?",
        "hello":          "Hey there! What can I do for you?",
        "help me":        "I'm here! Type 'help' to see all commands.",
        "what time is it":"Try: time",
        "what day is it": "Try: date",
    }

    @property
    def name(self) -> str:
        return "echo"

    def ask(self, text: str) -> str:
        low = text.lower().strip()
        for key, resp in self._RESPONSES.items():
            if key in low:
                return resp
        return (
            f"🤖 I heard: \"{text}\"\n"
            f"I don't have an AI backend configured yet.\n"
            f"Set OPENAI_API_KEY and ai_provider=openai in Settings to enable AI."
        )

    def ask_stream(self, text: str, on_chunk: Callable[[str], None]) -> str:
        response = self.ask(text)
        on_chunk(response)
        return response


# ── OpenAI ────────────────────────────────────────────────────────────────────

class OpenAIProvider(AIProvider):
    """
    Requires: pip install openai  +  OPENAI_API_KEY env var.
    Falls back to EchoProvider if openai package is missing or key absent.
    """

    def __init__(self, model: str = "gpt-4o-mini", timeout: int = 30,
                 system_prompt: str | None = None) -> None:
        self._model   = model
        self._timeout = timeout
        self._system  = system_prompt or (
            "You are JARVIS, a helpful Windows desktop AI companion. "
            "Be concise, friendly, and practical. "
            "Keep responses under 3 sentences unless detail is needed."
        )
        self._client  = None
        self._init()

    def _init(self) -> None:
        key = os.environ.get("OPENAI_API_KEY", "")
        if not key:
            log.warning("OPENAI_API_KEY not set — OpenAI provider unavailable.")
            return
        try:
            import openai
            self._client = openai.OpenAI(api_key=key, timeout=self._timeout)
            log.info("OpenAI provider ready (model=%s)", self._model)
        except ImportError:
            log.warning("openai package not installed. Run: pip install openai")

    @property
    def name(self) -> str:
        return f"openai/{self._model}"

    def ask(self, text: str) -> str:
        chunks: list[str] = []
        return self.ask_stream(text, chunks.append)

    def ask_stream(self, text: str, on_chunk: Callable[[str], None]) -> str:
        if self._client is None:
            return EchoProvider().ask_stream(text, on_chunk)
        try:
            t0 = time.monotonic()
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system",  "content": self._system},
                    {"role": "user",    "content": text},
                ],
                max_tokens=200,
                stream=True,
            )
            elapsed = time.monotonic() - t0
            parts: list[str] = []
            for event in resp:
                content = event.choices[0].delta.content
                if content:
                    parts.append(content)
                    on_chunk(content)
            reply = "".join(parts).strip()
            log.debug("OpenAI %.2fs: %s", elapsed, reply[:80])
            return reply
        except Exception as exc:
            log.warning("OpenAI error: %s", exc)
            message = f"⚠ AI error: {exc}"
            on_chunk(message)
            return message


# ── Factory ───────────────────────────────────────────────────────────────────

def get_provider(settings: "Settings") -> AIProvider:
    name = settings.get("ai_provider", "echo")
    if name == "openai":
        model   = settings.get("ai_model",   "gpt-4o-mini")
        timeout = settings.get("ai_timeout",  30)
        return OpenAIProvider(model=model, timeout=timeout)
    return EchoProvider()
