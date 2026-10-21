"""Provider-independent request gateway, fallback coordinator, and AI context policy."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
import uuid
from threading import Event
from typing import Any, Callable

from jarvis.ai import store
from jarvis.ai.adapters import (
    ADAPTERS, GenerationResult, ProviderError, RequestCancelled,
)
from jarvis.config.credential_store import CredentialStore
from jarvis.scheduling import database

log = logging.getLogger(__name__)

_DEFAULT_SYSTEM = (
    "You are JARVIS, a concise and helpful desktop companion. "
    "Answer the user's actual question. Never claim to have searched the web "
    "unless the configured provider performed a search."
)
_NO_CACHE_PATTERNS = re.compile(
    r"\b(now|today|current|currently|latest|recent|news|weather|stock|price|"
    r"exchange rate|account|balance|my order|right now|this week|tomorrow|"
    r"search|look up|find out|who won|breaking|this morning)\b",
    re.IGNORECASE,
)
_COMPLEX_PATTERNS = re.compile(
    r"\b(architecture|prove|analyze|analyse|complex|debug|refactor|"
    r"compare in depth|security review|design a system|code review|"
    r"coding|programming|implementation|algorithm)\b",
    re.IGNORECASE,
)
_ERROR_LABELS = {
    "rate_limit": "per-minute throttling",
    "quota_exhausted": "daily or account quota exhausted",
    "insufficient_credits": "insufficient paid credits",
    "invalid_auth": "invalid credentials",
    "unsupported_model": "model unavailable",
    "invalid_request": "invalid request parameters",
    "network": "network failure",
    "timeout": "request timed out",
    "transient": "temporary provider outage",
    "provider_unavailable": "provider unavailable",
}


def _error_label(category: str) -> str:
    return _ERROR_LABELS.get(category, category.replace("_", " "))


class AIGateway:
    """All remote LLM requests use this gateway for context, safety, cache, and fallback."""

    def __init__(
        self,
        settings,
        adapters: dict | None = None,
        credential_store: CredentialStore | None = None,
    ) -> None:
        self.settings = settings
        self.adapters = adapters or ADAPTERS
        self._credential_store = credential_store
        self.last_status = "Idle"
        self.last_provider = ""
        self.last_model = ""

    def _credentials(self) -> list[dict[str, Any]]:
        entries = self.settings.get("ai_credentials", [])
        return [
            dict(item) for item in entries
            if item.get("enabled", True) and item.get("provider") in self.adapters
        ]

    def _get_credential(self, entry: dict[str, Any]) -> str | None:
        credential_id = str(entry.get("id", ""))
        if not credential_id:
            return None
        if credential_id.startswith("env:"):
            env_name = str(entry.get("env_var", ""))
            return os.environ.get(env_name) if env_name else None
        if self._credential_store is None:
            self._credential_store = CredentialStore()
        return self._credential_store.get(credential_id)

    def _environment_key(self, provider: str, is_primary: bool) -> str | None:
        default_names = {
            "gemini": "GEMINI_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
            "grok": "XAI_API_KEY",
            "openai": "OPENAI_API_KEY",
        }
        if is_primary:
            name = str(
                self.settings.get("ai_api_key_env_var", "")
                or default_names[provider]
            )
        else:
            name = default_names[provider]
        return os.environ.get(name)

    def _credential_for_route(
        self, provider: str, credential_id: str = "", is_primary: bool = False
    ) -> tuple[str | None, dict[str, Any] | None]:
        entries = [item for item in self._credentials() if item["provider"] == provider]
        selected_id = credential_id
        if not selected_id and is_primary:
            selected_id = str(self.settings.get("ai_primary_credential_id", ""))
        if selected_id == "__environment__":
            return self._environment_key(provider, True), None
        if selected_id:
            entry = next((item for item in entries if item["id"] == selected_id), None)
            if entry:
                secret = self._get_credential(entry)
                if secret:
                    return secret, entry
            return None, entry
        for entry in entries:
            secret = self._get_credential(entry)
            if secret:
                return secret, entry
        return self._environment_key(provider, is_primary), None

    def _route_specs(self) -> list[dict[str, Any]]:
        provider = str(
            self.settings.get(
                "ai_primary_provider", self.settings.get("ai_provider", "gemini")
            )
        )
        model = str(
            self.settings.get(
                "ai_primary_model",
                self.settings.get("ai_model", "gemini-2.5-flash"),
            )
        ).strip()
        if provider not in self.adapters:
            raise ProviderError(
                provider, "provider_unavailable",
                f"Unsupported AI provider '{provider}'. Choose Gemini, OpenRouter, or Grok.",
            )
        enabled_providers = self.settings.get("ai_provider_enabled", {})
        if not enabled_providers.get(provider, True):
            self.last_status = f"{provider} is disabled in AI Pipeline Settings."
            raise ProviderError(
                provider, "provider_unavailable", self.last_status
            )
        if not model:
            self.last_status = "Select a model in AI Pipeline Settings."
            raise ProviderError(provider, "unsupported_model", "Select a model in AI Pipeline Settings.")
        primary = {
            "provider": provider,
            "model": model,
            "credential_id": str(self.settings.get("ai_primary_credential_id", "")),
            "primary": True,
        }
        routes = [primary]
        if self.settings.get("ai_fallback_enabled", True):
            for route in self.settings.get("ai_fallback_routes", []):
                if not route.get("enabled", True):
                    continue
                provider = str(route.get("provider", ""))
                model = str(route.get("model", "")).strip()
                if (
                    provider in self.adapters
                    and model
                    and self.settings.get("ai_provider_enabled", {}).get(provider, True)
                ):
                    routes.append({
                        "provider": provider,
                        "model": model,
                        "credential_id": str(route.get("credential_id", "")),
                        "primary": False,
                    })
        unique = []
        seen = set()
        for route in routes:
            key = (route["provider"], route["model"], route["credential_id"])
            if key not in seen:
                seen.add(key)
                unique.append(route)
        max_routes = max(0, int(self.settings.get("ai_max_fallback_attempts", 3)))
        return unique[:max_routes + 1]

    def _context(
        self, prompt: str
    ) -> tuple[str, list[dict[str, str]], str, str]:
        conversation_id = database.active_conversation_id()
        all_messages = database.conversation_messages(conversation_id)
        prior_messages = list(all_messages)
        if prior_messages and prior_messages[-1]["role"] == "user":
            if prior_messages[-1]["content"].strip() == prompt.strip():
                prior_messages.pop()

        threshold = max(6, int(self.settings.get("ai_summary_threshold", 30)))
        recent_count = max(1, int(self.settings.get("ai_recent_message_count", 8)))
        if len(all_messages) >= threshold:
            store.update_extractive_summary(
                conversation_id,
                all_messages,
                max(1, int(self.settings.get("ai_summary_recent_messages", recent_count))),
            )
        summary = store.get_summary(conversation_id)
        recent = prior_messages[-recent_count:]

        memory = store.search_memories(prompt, limit=4)
        system = str(self.settings.get("ai_system_prompt", _DEFAULT_SYSTEM)).strip()
        context_blocks = []
        if summary:
            context_blocks.append("Relevant conversation summary:\n" + summary)
        if memory:
            context_blocks.append(
                "Relevant user-approved memory:\n- " + "\n- ".join(memory)
            )
        max_chars = max(1000, int(self.settings.get("ai_context_max_chars", 12000)))
        remaining = max_chars
        messages: list[dict[str, str]] = []
        for item in reversed(recent):
            content = str(item["content"])
            if remaining <= 0:
                break
            content = content[-remaining:]
            messages.insert(0, {"role": item["role"], "content": content})
            remaining -= len(content)
        context_text = "\n".join(context_blocks)
        if len(context_text) > max_chars // 2:
            context_text = context_text[-(max_chars // 2):]
        if context_text:
            system = f"{system}\n\n{context_text}"
        context_fingerprint = store.fingerprint(
            system,
            json.dumps(messages, ensure_ascii=False, separators=(",", ":")),
        )
        messages.append({"role": "user", "content": prompt})
        return system, messages, context_fingerprint, conversation_id

    def _selected_model(self, route: dict[str, Any], prompt: str) -> str:
        if (
            route["primary"]
            and self.settings.get("ai_advanced_route_enabled", False)
            and _COMPLEX_PATTERNS.search(prompt)
        ):
            advanced = str(self.settings.get("ai_advanced_model", "")).strip()
            if advanced:
                return advanced
        return route["model"]

    def generate(
        self,
        prompt: str,
        on_chunk: Callable[[str], None] | None = None,
        cancel_event: Event | None = None,
        on_reset: Callable[[], None] | None = None,
    ) -> str:
        prompt = prompt.strip()
        if not prompt:
            return ""
        cancel_event = cancel_event or Event()
        request_id = uuid.uuid4().hex
        started = time.monotonic()
        system, messages, context_fingerprint, conversation_id = self._context(prompt)
        routes = self._route_specs()
        primary_model = self._selected_model(routes[0], prompt)
        cacheable = bool(
            self.settings.get("ai_cache_enabled", True)
            and not _NO_CACHE_PATTERNS.search(prompt)
        )
        output_limit = max(1, int(self.settings.get("ai_max_output_tokens", 512)))
        cache_key = store.fingerprint(
            str(store.CACHE_POLICY_VERSION),
            routes[0]["provider"],
            primary_model,
            store.normalize_prompt(prompt),
            system,
            context_fingerprint,
            str(output_limit),
            json.dumps(
                {
                    "routes": routes,
                    "primary_key_env_var": self.settings.get(
                        "ai_api_key_env_var", ""
                    ),
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
        if cacheable:
            cached = store.get_cached(cache_key)
            if cached:
                elapsed = int((time.monotonic() - started) * 1000)
                input_tokens = store.estimate_tokens(
                    system + "\n" + json.dumps(messages, ensure_ascii=False)
                )
                output_tokens = store.estimate_tokens(cached["response"])
                store.record_usage(
                    request_id, cached["provider"], cached["model"], "cache",
                    input_tokens, output_tokens, cache_hit=True, elapsed_ms=elapsed,
                )
                self.last_provider = str(cached["provider"])
                self.last_model = str(cached["model"])
                self.last_status = f"Cache hit — {self.last_provider}/{self.last_model}"
                log.info(
                    "AI request=%s provider=%s model=%s elapsed_ms=%d "
                    "input_tokens=%d output_tokens=%d cache=hit",
                    request_id, self.last_provider, self.last_model, elapsed,
                    input_tokens, output_tokens,
                )
                if on_chunk:
                    on_chunk(str(cached["response"]))
                return str(cached["response"])

        self.last_status = "Requesting provider…"
        failures: list[str] = []
        tried: set[tuple[str, str, str]] = set()
        exhausted_projects: set[str] = set()
        exhausted_credentials: set[str] = set()
        attempts_total = 0
        max_retries = max(0, int(self.settings.get("ai_max_retries", 1)))
        timeout = max(1, int(self.settings.get("ai_timeout", 30)))
        final_error: ProviderError | None = None
        for route_index, route in enumerate(routes):
            provider = route["provider"]
            model = self._selected_model(route, prompt)
            try:
                credentials = self._credential_candidates(
                    route, exhausted_projects, exhausted_credentials
                )
            except Exception as exc:
                failures.append(f"{provider}: secure credential store unavailable")
                final_error = ProviderError(provider, "invalid_auth", str(exc))
                store.record_usage(
                    request_id, provider, model, "failed",
                    error_category="invalid_auth",
                )
                continue
            if not credentials:
                failures.append(f"{provider}: no configured credential")
                final_error = ProviderError(
                    provider, "invalid_auth",
                    f"No API key configured for {provider}. Add one in AI Pipeline Settings.",
                )
                store.record_usage(
                    request_id, provider, model, "failed",
                    error_category="invalid_auth",
                )
                continue

            credential_index = 0
            queued_credentials = list(credentials)
            while credential_index < len(queued_credentials):
                secret, metadata = queued_credentials[credential_index]
                credential_index += 1
                if not secret:
                    continue
                credential_id = str(metadata.get("id", "")) if metadata else "environment"
                attempt_key = (provider, model, credential_id)
                if attempt_key in tried:
                    continue
                tried.add(attempt_key)
                adapter = self.adapters[provider]
                retry = 0
                while True:
                    if cancel_event.is_set():
                        raise RequestCancelled()
                    attempts_total += 1
                    attempt_chunks: list[str] = []
                    attempt_started = time.monotonic()
                    try:
                        def forward_chunk(chunk: str) -> None:
                            attempt_chunks.append(chunk)
                            if on_chunk:
                                on_chunk(chunk)

                        result: GenerationResult = adapter.generate(
                            model, system, messages, secret, output_limit,
                            timeout, cancel_event,
                            on_chunk=forward_chunk if on_chunk else None,
                        )
                        if cancel_event.is_set():
                            raise RequestCancelled()
                        if not result.text.strip():
                            raise ProviderError(
                                provider, "invalid_response",
                                "Provider returned an empty response.",
                            )
                        elapsed = int((time.monotonic() - attempt_started) * 1000)
                        input_tokens = result.input_tokens or store.estimate_tokens(
                            system + "\n" + json.dumps(messages, ensure_ascii=False)
                        )
                        output_tokens = result.output_tokens or store.estimate_tokens(result.text)
                        store.record_usage(
                            request_id, provider, model, "success",
                            input_tokens, output_tokens, elapsed_ms=elapsed,
                        )
                        self.last_provider = provider
                        self.last_model = model
                        fallback_note = f" after fallback ({failures[-1]})" if failures else ""
                        self.last_status = (
                            f"Connected — {provider}/{model}{fallback_note}"
                        )
                        if cacheable:
                            store.save_cached(
                                cache_key, prompt, provider, model,
                                context_fingerprint, result.text,
                                max(1, int(self.settings.get("ai_cache_expiry_minutes", 60))) * 60,
                            )
                        log.info(
                            "AI request=%s provider=%s model=%s elapsed_ms=%d "
                            "input_tokens=%d output_tokens=%d cache=miss",
                            request_id, provider, model, elapsed,
                            input_tokens, output_tokens,
                        )
                        if on_chunk and not attempt_chunks:
                            on_chunk(result.text)
                        return result.text
                    except RequestCancelled:
                        if attempt_chunks and on_reset:
                            on_reset()
                        elapsed = int((time.monotonic() - attempt_started) * 1000)
                        store.record_usage(
                            request_id, provider, model, "cancelled",
                            elapsed_ms=elapsed, error_category="cancelled",
                        )
                        self.last_status = "Request cancelled."
                        raise
                    except ProviderError as exc:
                        if attempt_chunks and on_reset:
                            on_reset()
                        final_error = exc
                        elapsed = int((time.monotonic() - attempt_started) * 1000)
                        store.record_usage(
                            request_id, provider, model, "failed",
                            elapsed_ms=elapsed, error_category=exc.category,
                        )
                        failures.append(
                            f"{provider}/{model}: {_error_label(exc.category)}"
                        )
                        log.warning(
                            "AI request=%s provider=%s model=%s status=failed "
                            "category=%s elapsed_ms=%d cache=miss",
                            request_id, provider, model, exc.category, elapsed,
                        )
                        if exc.category == "invalid_request":
                            self.last_status = "Invalid request; fallback stopped."
                            raise
                        if exc.category == "invalid_auth" and metadata:
                            self._disable_credential(metadata)
                        if exc.category == "quota_exhausted":
                            exhausted_credentials.add(credential_id)
                            project = str((metadata or {}).get("project", ""))
                            if project:
                                exhausted_projects.add(project)
                        if provider == "gemini" and exc.category in {
                            "invalid_auth", "quota_exhausted"
                        }:
                            candidates = self._other_gemini_credentials(
                                metadata,
                                tried,
                                different_project=exc.category == "quota_exhausted",
                            )
                            for candidate in candidates:
                                queued_credentials.append(candidate)
                            if candidates:
                                log.info(
                                    "AI request=%s Gemini credential fallback after %s",
                                    request_id, exc.category,
                                )
                        elif exc.category == "invalid_auth":
                            candidates = self._other_provider_credentials(provider, tried)
                            queued_credentials.extend(candidates)
                            if candidates:
                                log.info(
                                    "AI request=%s provider=%s credential fallback after invalid_auth",
                                    request_id, provider,
                                )
                        if exc.category in {"transient", "network", "timeout"} and retry < max_retries:
                            retry_cap = max(
                                0, int(self.settings.get("ai_retry_wait_cap_seconds", 5))
                            )
                            if exc.retry_after is not None:
                                delay = max(0.0, exc.retry_after)
                                if delay > retry_cap:
                                    break
                            else:
                                delay = min(
                                    0.5 * (2 ** (retry - 1)), retry_cap
                                )
                            retry += 1
                            if cancel_event.wait(delay):
                                raise RequestCancelled()
                            continue
                        break
            if route_index + 1 < len(routes):
                log.info(
                    "AI request=%s fallback from %s/%s after %s",
                    request_id, provider, model,
                    final_error.category if final_error else "unavailable",
                )

        category = final_error.category if final_error else "provider_unavailable"
        self.last_status = (
            f"All configured providers failed ({_error_label(category)}). "
            "Retry the request."
        )
        reason = "; ".join(failures) or "No configured provider succeeded."
        raise ProviderError(
            final_error.provider if final_error else "gateway",
            category,
            f"AI request failed after {attempts_total} attempt(s): {reason}. "
            "You can retry once the provider or quota is available.",
        )

    def _credential_candidates(
        self,
        route: dict[str, Any],
        exhausted_projects: set[str] | None = None,
        exhausted_credentials: set[str] | None = None,
    ) -> list[tuple[str, dict[str, Any] | None]]:
        provider = route["provider"]
        primary_id = route["credential_id"]
        if route["primary"] and not primary_id:
            primary_id = str(self.settings.get("ai_primary_credential_id", ""))
        entries = [
            item for item in self._credentials()
            if item.get("provider") == provider
        ]
        use_environment = primary_id == "__environment__"
        if use_environment:
            entries = []
        elif primary_id:
            entries = [item for item in entries if item.get("id") == primary_id]
            if not entries:
                return []
        for item in entries:
            credential_id = str(item.get("id", ""))
            project = str(item.get("project", ""))
            if credential_id in (exhausted_credentials or set()):
                continue
            if project and project in (exhausted_projects or set()):
                continue
            secret = self._get_credential(item)
            if secret:
                return [(secret, item)]
        environment_key = self._environment_key(provider, bool(route["primary"]))
        if (
            environment_key
            and (use_environment or not entries)
            and "environment" not in (exhausted_credentials or set())
        ):
            return [(environment_key, None)]
        return []

    def _disable_credential(self, credential: dict[str, Any]) -> None:
        credential_id = str(credential.get("id", ""))
        if not credential_id:
            return
        entries = [
            dict(item) for item in self.settings.get("ai_credentials", [])
        ]
        for entry in entries:
            if str(entry.get("id", "")) == credential_id:
                entry["enabled"] = False
        self.settings.set("ai_credentials", entries)
        if self.settings.get("ai_primary_credential_id") == credential_id:
            replacement = next(
                (
                    entry.get("id")
                    for entry in entries
                    if entry.get("provider") == credential.get("provider")
                    and entry.get("enabled", True)
                ),
                "",
            )
            self.settings.set("ai_primary_credential_id", replacement)
        self.settings.save()

    def _other_gemini_credentials(
        self,
        failed_entry: dict[str, Any] | None,
        tried: set[tuple[str, str, str]],
        different_project: bool,
    ) -> list[tuple[str, dict[str, Any]]]:
        candidates = []
        for entry in self._credentials():
            if entry.get("provider") != "gemini":
                continue
            if failed_entry and entry.get("id") == failed_entry.get("id"):
                continue
            if different_project:
                old_project = (failed_entry or {}).get("project")
                new_project = entry.get("project")
                if not old_project or not new_project or old_project == new_project:
                    continue
            # A model is not part of the credential identity; skip any credential
            # already attempted against this Gemini route.
            credential_id = str(entry.get("id", ""))
            if any(
                provider == "gemini" and cred_id == credential_id
                for provider, _model, cred_id in tried
            ):
                continue
            secret = self._get_credential(entry)
            if secret:
                candidates.append((secret, entry))
        return candidates

    def _other_provider_credentials(
        self,
        provider: str,
        tried: set[tuple[str, str, str]],
    ) -> list[tuple[str, dict[str, Any]]]:
        candidates = []
        for entry in self._credentials():
            credential_id = str(entry.get("id", ""))
            if entry.get("provider") != provider or any(
                used_provider == provider and used_id == credential_id
                for used_provider, _used_model, used_id in tried
            ):
                continue
            secret = self._get_credential(entry)
            if secret:
                candidates.append((secret, entry))
        return candidates

    def discover_models(
        self, provider: str, force_refresh: bool = False, credential_id: str = ""
    ) -> list[dict]:
        if provider not in self.adapters:
            raise ValueError(f"Unsupported provider '{provider}'.")
        ttl = max(60, int(self.settings.get("ai_model_catalog_ttl_seconds", 3600)))
        if not force_refresh:
            cached = store.cached_model_catalog(provider, ttl)
            if cached:
                return cached
        route = {"provider": provider, "primary": provider == self.settings.get("ai_primary_provider", "gemini")}
        secret, _metadata = self._credential_for_route(provider, credential_id, route["primary"])
        if not secret and provider != "openrouter":
            raise ProviderError(
                provider, "invalid_auth",
                f"Configure an API key for {provider} to discover its models.",
            )
        models = self.adapters[provider].list_models(
            secret or "", max(1, int(self.settings.get("ai_timeout", 30)))
        )
        store.save_model_catalog(provider, models)
        self.last_status = f"Discovered {len(models)} models for {provider}."
        return models

    def test_connection(self, provider: str, credential_id: str = "") -> str:
        if provider not in self.adapters:
            raise ValueError(f"Unsupported provider '{provider}'.")
        route = {
            "provider": provider,
            "primary": provider == self.settings.get("ai_primary_provider", "gemini"),
        }
        secret, _metadata = self._credential_for_route(provider, credential_id, route["primary"])
        if not secret:
            raise ProviderError(
                provider, "invalid_auth", f"No API key configured for {provider}."
            )
        models = self.adapters[provider].list_models(
            secret or "", max(1, int(self.settings.get("ai_timeout", 30)))
        )
        store.save_model_catalog(provider, models)
        self.last_status = f"Connected — {provider}; discovered {len(models)} model(s)."
        return f"Connected to {provider}; discovered {len(models)} model(s)."
