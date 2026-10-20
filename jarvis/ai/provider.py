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
import json
import urllib.error
import urllib.parse
import urllib.request
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

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        timeout: int = 30,
        system_prompt: str | None = None,
        api_key_env_var: str = "OPENAI_API_KEY",
    ) -> None:
        self._model   = model
        self._timeout = timeout
        self._api_key_env_var = api_key_env_var
        self._system  = system_prompt or (
            "You are JARVIS, a helpful Windows desktop AI companion. "
            "Be concise, friendly, and practical. "
            "Keep responses under 3 sentences unless detail is needed."
        )
        self._client  = None
        self._init()

    def _init(self) -> None:
        key = os.environ.get(self._api_key_env_var, "")
        if not key:
            log.warning("%s not set — OpenAI provider unavailable.", self._api_key_env_var)
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
            message = (
                f"⚠ AI provider is unavailable. Check {self._api_key_env_var} and install "
                "the optional openai package; local commands remain available."
            )
            on_chunk(message)
            return message
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


class GeminiProvider(AIProvider):
    """Google Gemini REST provider using an API key from the environment."""

    def __init__(
        self,
        model: str = "gemini-2.5-flash",
        timeout: int = 30,
        api_key_env_var: str = "GEMINI_API_KEY",
    ) -> None:
        self._model = model
        self._timeout = timeout
        self._api_key_env_var = api_key_env_var

    @property
    def name(self) -> str:
        return f"gemini/{self._model}"

    def ask(self, text: str) -> str:
        api_key = os.environ.get(self._api_key_env_var, "")
        if not api_key:
            return (
                f"⚠ Gemini is unavailable. Set the {self._api_key_env_var} "
                "environment variable; local commands remain available."
            )
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{urllib.parse.quote(self._model, safe='')}:generateContent"
        )
        payload = {
            "contents": [{"role": "user", "parts": [{"text": text}]}],
            "generationConfig": {"maxOutputTokens": 512},
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
            candidates = result.get("candidates", [])
            parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
            answer = "\n".join(
                str(part["text"]).strip()
                for part in parts
                if isinstance(part, dict) and part.get("text")
            ).strip()
            if not answer:
                return "⚠ Gemini returned no text. Try a different model or prompt."
            return answer
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("error", {}).get("message", "")
            except (ValueError, UnicodeDecodeError):
                detail = ""
            detail = str(detail).replace(api_key, "[redacted]")
            return (
                f"⚠ Gemini request failed (HTTP {exc.code}). "
                f"{detail or 'Check the model name, quota, and API key.'}"
            )
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return f"⚠ Gemini request failed: {str(exc).replace(api_key, '[redacted]')}"
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            log.warning("Invalid Gemini response: %s", type(exc).__name__)
            return "⚠ Gemini returned an invalid response. Please retry."

    def ask_stream(self, text: str, on_chunk: Callable[[str], None]) -> str:
        answer = self.ask(text)
        on_chunk(answer)
        return answer


# ── Factory ───────────────────────────────────────────────────────────────────

def get_provider(settings: "Settings") -> AIProvider:
    name = settings.get("ai_provider", "echo")
    if name == "openai":
        model   = settings.get("ai_model",   "gpt-4o-mini")
        timeout = settings.get("ai_timeout",  30)
        env_var = settings.get("ai_api_key_env_var", "OPENAI_API_KEY")
        return OpenAIProvider(
            model=model, timeout=timeout, api_key_env_var=env_var
        )
    if name == "gemini":
        model = settings.get("ai_model", "") or "gemini-2.5-flash"
        timeout = settings.get("ai_timeout", 30)
        env_var = settings.get("ai_api_key_env_var", "GEMINI_API_KEY")
        return GeminiProvider(
            model=model, timeout=timeout, api_key_env_var=env_var
        )
    return EchoProvider()
