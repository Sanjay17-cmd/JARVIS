from __future__ import annotations

import json
import io
import urllib.error
from email.message import Message
from threading import Event

import pytest

from jarvis.ai.adapters import (
    GeminiAdapter,
    GenerationResult,
    GrokAdapter,
    OpenAIAdapter,
    OpenRouterAdapter,
    ProviderError,
    RequestCancelled,
    _classify_error,
)
from jarvis.ai.gateway import AIGateway
from jarvis.ai import store
from jarvis.scheduling import database


class Settings:
    def __init__(self, **values):
        self.values = {
            "ai_primary_provider": "gemini",
            "ai_primary_model": "gemini-test",
            "ai_primary_credential_id": "",
            "ai_credentials": [],
            "ai_fallback_enabled": False,
            "ai_fallback_routes": [],
            "ai_provider_enabled": {
                "gemini": True, "openrouter": True, "grok": True,
            },
            "ai_cache_enabled": False,
            "ai_max_retries": 0,
            "ai_retry_wait_cap_seconds": 0,
            "ai_timeout": 2,
            "ai_max_output_tokens": 64,
            **values,
        }
        self.saves = 0

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value

    def save(self):
        self.saves += 1


class CredentialStoreStub:
    def __init__(self, values):
        self.values = values

    def get(self, credential_id):
        return self.values.get(credential_id)


class FakeAdapter:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.keys = []
        self.models = []

    def generate(self, model, system, messages, key, output_limit, timeout,
                 cancel_event, on_chunk=None):
        self.keys.append(key)
        self.models.append(model)
        outcome = self.outcomes.pop(0) if self.outcomes else GenerationResult("ok")
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def list_models(self, key, timeout):
        return [{"id": "model-a", "name": "Model A", "free": True}]


@pytest.fixture
def isolated_ai_store(tmp_path, monkeypatch):
    database.close()
    monkeypatch.setattr(database, "_db_path", lambda: tmp_path / "jarvis.db")
    database._conn = None
    yield
    database.close()
    database._conn = None


@pytest.fixture
def mocked_store(monkeypatch):
    cache = {}
    records = []
    monkeypatch.setattr(store, "get_cached", lambda key: cache.get(key))
    monkeypatch.setattr(
        store,
        "save_cached",
        lambda key, prompt, provider, model, context, response, ttl: cache.__setitem__(
            key, {"provider": provider, "model": model, "response": response}
        ),
    )
    monkeypatch.setattr(store, "record_usage", lambda *args, **kwargs: records.append((args, kwargs)))
    monkeypatch.setattr(store, "estimate_tokens", lambda text: max(1, len(text) // 4))
    return cache, records


def gateway_for(settings, adapter, credentials=None):
    return AIGateway(
        settings,
        adapters={"gemini": adapter, "openrouter": adapter, "grok": adapter},
        credential_store=CredentialStoreStub(credentials or {}),
    )


def set_context(gateway, fingerprint="context-1"):
    gateway._context = lambda prompt: (
        "system",
        [{"role": "user", "content": prompt}],
        fingerprint,
        "conversation",
    )


@pytest.mark.parametrize(
    ("adapter_type", "provider", "payload"),
    [
        (
            GeminiAdapter, "gemini",
            {"candidates": [{"content": {"parts": [{"text": "Gemini answer"}]}}]},
        ),
        (
            OpenRouterAdapter, "openrouter",
            {"choices": [{"message": {"content": "OpenRouter answer"}}]},
        ),
        (
            GrokAdapter, "grok",
            {"choices": [{"message": {"content": "Grok answer"}}]},
        ),
        (
            OpenAIAdapter, "openai",
            {"choices": [{"message": {"content": "OpenAI answer"}}]},
        ),
    ],
)
def test_provider_adapters_generate_with_supported_http_shapes(
    adapter_type, provider, payload, monkeypatch
):
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps(payload).encode()

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    adapter = adapter_type()
    result = adapter.generate(
        "model-id", "system", [{"role": "user", "content": "hello"}],
        "fake-key", 32, 3, Event(),
    )

    assert result.text.endswith("answer")
    assert captured["timeout"] == 3
    if provider == "gemini":
        assert captured["request"].get_header("X-goog-api-key") == "fake-key"
    else:
        assert captured["request"].get_header("Authorization") == "Bearer fake-key"


def test_provider_errors_redact_api_keys_from_response_bodies(monkeypatch):
    secret = "fake-private-key"
    body = json.dumps({"error": {"message": f"Rejected {secret}"}}).encode()
    headers = Message()
    error = urllib.error.HTTPError(
        "https://api.example.test", 401, "Unauthorized", headers, io.BytesIO(body)
    )

    def fail_request(*_args, **_kwargs):
        raise error

    monkeypatch.setattr("urllib.request.urlopen", fail_request)
    with pytest.raises(ProviderError) as caught:
        OpenRouterAdapter()._request_json(
            "https://api.example.test", secret, 1
        )
    assert secret not in str(caught.value)


def test_gemini_discovery_excludes_non_text_models_and_prefers_stable_versions(
    monkeypatch,
):
    adapter = GeminiAdapter()
    monkeypatch.setattr(
        adapter,
        "_request_json",
        lambda *_args, **_kwargs: {
            "models": [
                {"name": "models/gemini-2.5-flash", "displayName": "Flash 2.5",
                 "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-3.8-flash-tts", "displayName": "Flash TTS",
                 "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-4-argon", "displayName": "Argon",
                 "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-4-preview", "displayName": "Preview",
                 "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-5-audio", "displayName": "Audio",
                 "supportedGenerationMethods": ["generateAudio"]},
            ]
        },
    )

    models = adapter.list_models("fake-key", 3)

    assert [item["id"] for item in models] == [
        "gemini-4-argon",
        "gemini-2.5-flash",
        "gemini-4-preview",
    ]


def test_refresh_selects_newest_stable_account_model_when_using_default(
    isolated_ai_store, monkeypatch, qtbot
):
    from jarvis.ui.ai_pipeline_dialog import AIPipelineDialog

    models = [
        {"id": "gemini-2.5-flash", "name": "Flash 2.5"},
        {"id": "gemini-4-argon", "name": "Argon"},
        {"id": "gemini-5-preview", "name": "Preview"},
    ]
    monkeypatch.setattr(store, "cached_model_catalog", lambda *_args: models)

    class Gateway:
        last_status = "Idle"

        def discover_models(self, *_args, **_kwargs):
            return models

    settings = Settings(ai_primary_model="gemini-2.5-flash")
    dialog = AIPipelineDialog(settings, gateway=Gateway())
    qtbot.addWidget(dialog)
    assert dialog.model.currentData() == "gemini-2.5-flash"

    dialog._refresh_models()

    assert dialog.model.currentData() == "gemini-4-argon"
    dialog.close()


def test_gateway_cache_hit_skips_provider_request(mocked_store, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    adapter = FakeAdapter(GenerationResult("cached answer"))
    settings = Settings(ai_cache_enabled=True)
    gateway = gateway_for(settings, adapter)
    set_context(gateway)

    assert gateway.generate("Explain a stable concept") == "cached answer"
    assert gateway.generate("Explain a stable concept") == "cached answer"
    assert adapter.keys == ["fake-key"]
    assert gateway.last_status.startswith("Cache hit")


def test_gateway_cache_key_changes_with_context(mocked_store, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    adapter = FakeAdapter(GenerationResult("first"), GenerationResult("second"))
    settings = Settings(ai_cache_enabled=True)
    gateway = gateway_for(settings, adapter)
    context = ["summary-a"]
    gateway._context = lambda prompt: (
        "system", [{"role": "user", "content": prompt}], context[0], "conversation"
    )

    assert gateway.generate("Explain a stable concept") == "first"
    context[0] = "summary-b"
    assert gateway.generate("Explain a stable concept") == "second"
    assert len(adapter.keys) == 2


def test_model_catalog_is_cached_and_refreshable(monkeypatch):
    adapter = FakeAdapter()
    settings = Settings()
    gateway = gateway_for(settings, adapter)
    calls = []
    monkeypatch.setattr(
        store, "cached_model_catalog",
        lambda provider, ttl: calls.append(("cache", provider)) or (
            [{"id": "cached-model", "name": "Cached"}]
            if len(calls) == 1 else []
        ),
    )
    monkeypatch.setattr(store, "save_model_catalog", lambda provider, models: calls.append(("save", provider)))
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")

    assert gateway.discover_models("gemini")[0]["id"] == "cached-model"
    assert calls == [("cache", "gemini")]
    assert gateway.discover_models("gemini", force_refresh=True)[0]["id"] == "model-a"
    assert calls[-1] == ("save", "gemini")


def test_environment_credential_selection_is_explicit(mocked_store, monkeypatch):
    monkeypatch.setenv("MY_GEMINI_ENV_KEY", "environment-key")
    adapter = FakeAdapter(GenerationResult("answer"))
    settings = Settings(
        ai_primary_credential_id="__environment__",
        ai_api_key_env_var="MY_GEMINI_ENV_KEY",
        ai_credentials=[
            {"id": "stored-key", "provider": "gemini", "enabled": True},
        ],
    )
    gateway = gateway_for(settings, adapter, {"stored-key": "stored-secret"})
    set_context(gateway)

    assert gateway.generate("question") == "answer"
    assert adapter.keys == ["environment-key"]


def test_gemini_quota_does_not_rotate_keys_in_same_project(mocked_store):
    adapter = FakeAdapter(
        ProviderError("gemini", "quota_exhausted", "daily quota exceeded")
    )
    settings = Settings(
        ai_primary_credential_id="key-a",
        ai_credentials=[
            {"id": "key-a", "provider": "gemini", "project": "project-one"},
            {"id": "key-b", "provider": "gemini", "project": "project-one"},
        ],
    )
    gateway = gateway_for(settings, adapter, {"key-a": "secret-a", "key-b": "secret-b"})
    set_context(gateway)

    with pytest.raises(ProviderError):
        gateway.generate("question")
    assert adapter.keys == ["secret-a"]


def test_gemini_quota_tries_another_known_project(mocked_store):
    adapter = FakeAdapter(
        ProviderError("gemini", "quota_exhausted", "daily quota exceeded"),
        GenerationResult("answer from another project"),
    )
    settings = Settings(
        ai_primary_credential_id="key-a",
        ai_credentials=[
            {"id": "key-a", "provider": "gemini", "project": "project-one"},
            {"id": "key-b", "provider": "gemini", "project": "project-two"},
        ],
    )
    gateway = gateway_for(settings, adapter, {"key-a": "secret-a", "key-b": "secret-b"})
    set_context(gateway)

    assert gateway.generate("question") == "answer from another project"
    assert adapter.keys == ["secret-a", "secret-b"]


def test_invalid_openrouter_key_is_disabled_and_next_key_is_used(mocked_store, caplog):
    adapter = FakeAdapter(
        ProviderError("openrouter", "invalid_auth", "invalid key"),
        GenerationResult("answer"),
    )
    settings = Settings(
        ai_primary_provider="openrouter",
        ai_primary_model="router-model",
        ai_primary_credential_id="key-a",
        ai_credentials=[
            {"id": "key-a", "provider": "openrouter", "enabled": True},
            {"id": "key-b", "provider": "openrouter", "enabled": True},
        ],
    )
    gateway = gateway_for(settings, adapter, {"key-a": "secret-a", "key-b": "secret-b"})
    set_context(gateway)

    assert gateway.generate("question") == "answer"
    assert adapter.keys == ["secret-a", "secret-b"]
    assert settings.values["ai_credentials"][0]["enabled"] is False
    assert settings.get("ai_primary_credential_id") == "key-b"
    assert "secret-a" not in json.dumps(settings.values)
    assert "secret-a" not in caplog.text


def test_rate_limit_does_not_rotate_gemini_credentials(mocked_store):
    adapter = FakeAdapter(ProviderError("gemini", "rate_limit", "slow down"))
    settings = Settings(
        ai_primary_credential_id="key-a",
        ai_credentials=[
            {"id": "key-a", "provider": "gemini", "project": "project-one"},
            {"id": "key-b", "provider": "gemini", "project": "project-two"},
        ],
    )
    gateway = gateway_for(settings, adapter, {"key-a": "secret-a", "key-b": "secret-b"})
    set_context(gateway)

    with pytest.raises(ProviderError):
        gateway.generate("question")
    assert adapter.keys == ["secret-a"]


@pytest.mark.parametrize(
    ("status", "message", "category"),
    [
        (401, "bad key", "invalid_auth"),
        (402, "payment required", "insufficient_credits"),
        (429, "too many requests", "rate_limit"),
        (429, "You exceeded your current quota", "quota_exhausted"),
        (404, "model not found", "unsupported_model"),
        (400, "invalid parameter", "invalid_request"),
        (503, "service unavailable", "transient"),
        (504, "gateway timeout", "transient"),
    ],
)
def test_provider_error_categories(status, message, category):
    assert _classify_error("gemini", status, message) == category


def test_invalid_request_stops_before_fallback(mocked_store, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "router-key")
    primary = FakeAdapter(ProviderError("gemini", "invalid_request", "bad request"))
    fallback = FakeAdapter(GenerationResult("must not run"))
    settings = Settings(
        ai_fallback_enabled=True,
        ai_fallback_routes=[{
            "provider": "openrouter", "model": "router-model", "enabled": True,
        }],
    )
    gateway = AIGateway(
        settings,
        {"gemini": primary, "openrouter": fallback, "grok": fallback},
    )
    set_context(gateway)

    with pytest.raises(ProviderError):
        gateway.generate("question")
    assert fallback.keys == []


def test_fallback_route_cap_can_disable_all_fallbacks(mocked_store, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "router-key")
    primary = FakeAdapter(ProviderError("gemini", "network", "offline"))
    fallback = FakeAdapter(GenerationResult("must not run"))
    settings = Settings(
        ai_max_fallback_attempts=0,
        ai_fallback_enabled=True,
        ai_fallback_routes=[{
            "provider": "openrouter", "model": "router-model", "enabled": True,
        }],
    )
    gateway = AIGateway(
        settings,
        {"gemini": primary, "openrouter": fallback, "grok": fallback},
    )
    set_context(gateway)

    with pytest.raises(ProviderError):
        gateway.generate("question")
    assert primary.keys == ["gemini-key"]
    assert fallback.keys == []


def test_unsupported_model_uses_configured_fallback(mocked_store, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "router-key")
    primary = FakeAdapter(
        ProviderError("gemini", "unsupported_model", "model unavailable")
    )
    fallback = FakeAdapter(GenerationResult("supported fallback"))
    settings = Settings(
        ai_fallback_enabled=True,
        ai_fallback_routes=[{
            "provider": "openrouter", "model": "supported-model", "enabled": True,
        }],
    )
    gateway = AIGateway(
        settings,
        {"gemini": primary, "openrouter": fallback, "grok": fallback},
    )
    set_context(gateway)

    assert gateway.generate("question") == "supported fallback"
    assert fallback.models == ["supported-model"]


def test_all_provider_failures_return_error_without_success_shaped_answer(
    mocked_store, monkeypatch
):
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "router-key")
    primary = FakeAdapter(ProviderError("gemini", "network", "offline"))
    fallback = FakeAdapter(ProviderError("openrouter", "timeout", "timed out"))
    settings = Settings(
        ai_fallback_enabled=True,
        ai_fallback_routes=[{
            "provider": "openrouter", "model": "router-model", "enabled": True,
        }],
    )
    gateway = AIGateway(
        settings,
        {"gemini": primary, "openrouter": fallback, "grok": fallback},
    )
    set_context(gateway)

    with pytest.raises(ProviderError, match="AI request failed"):
        gateway.generate("question")
    assert primary.keys == ["gemini-key"]
    assert fallback.keys == ["router-key"]
    assert "Retry" in gateway.last_status


def test_retry_after_beyond_wait_cap_is_not_ignored(mocked_store, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "router-key")
    primary = FakeAdapter(
        ProviderError(
            "gemini", "transient", "temporarily unavailable", retry_after=30
        )
    )
    fallback = FakeAdapter(GenerationResult("fallback answer"))
    settings = Settings(
        ai_max_retries=2,
        ai_retry_wait_cap_seconds=2,
        ai_fallback_enabled=True,
        ai_fallback_routes=[{
            "provider": "openrouter", "model": "router-model", "enabled": True,
        }],
    )
    gateway = AIGateway(
        settings,
        {"gemini": primary, "openrouter": fallback, "grok": fallback},
    )
    set_context(gateway)

    assert gateway.generate("question") == "fallback answer"
    assert primary.keys == ["gemini-key"]
    assert fallback.keys == ["router-key"]


def test_streaming_fallback_resets_partial_primary_output(mocked_store, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "router-key")

    class PartialFailure(FakeAdapter):
        def generate(self, model, system, messages, key, output_limit, timeout,
                     cancel_event, on_chunk=None):
            self.keys.append(key)
            on_chunk("partial primary") if on_chunk else None
            raise ProviderError("gemini", "network", "offline")

    primary = PartialFailure()
    fallback = FakeAdapter(GenerationResult("fallback answer"))
    settings = Settings(
        ai_fallback_enabled=True,
        ai_fallback_routes=[{
            "provider": "openrouter", "model": "router-model", "enabled": True,
        }],
    )
    gateway = AIGateway(
        settings,
        {"gemini": primary, "openrouter": fallback, "grok": fallback},
    )
    set_context(gateway)
    chunks = []
    resets = []

    assert gateway.generate("question", chunks.append, Event(), lambda: resets.append(True)) == "fallback answer"
    assert chunks == ["partial primary", "fallback answer"]
    assert resets == [True]


def test_cancelled_generation_is_not_cached_or_returned(mocked_store, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")

    class CancellingAdapter(FakeAdapter):
        def generate(self, model, system, messages, key, output_limit, timeout,
                     cancel_event, on_chunk=None):
            self.keys.append(key)
            cancel_event.set()
            return GenerationResult("stale answer")

    adapter = CancellingAdapter()
    settings = Settings(ai_cache_enabled=True)
    gateway = gateway_for(settings, adapter)
    set_context(gateway)

    with pytest.raises(RequestCancelled):
        gateway.generate("question")
    assert adapter.keys == ["gemini-key"]
    assert mocked_store[0] == {}


def test_fallback_order_and_retry_cap(mocked_store, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "router-key")
    gemini = FakeAdapter(
        ProviderError("gemini", "network", "offline"),
        ProviderError("gemini", "network", "offline"),
    )
    router = FakeAdapter(GenerationResult("fallback answer"))
    settings = Settings(
        ai_max_retries=1,
        ai_fallback_enabled=True,
        ai_fallback_routes=[{
            "provider": "openrouter", "model": "router-model", "enabled": True,
        }],
    )
    gateway = AIGateway(
        settings, {"gemini": gemini, "openrouter": router, "grok": router},
    )
    set_context(gateway)

    assert gateway.generate("question") == "fallback answer"
    assert gemini.keys == ["gemini-key", "gemini-key"]
    assert router.keys == ["router-key"]


def test_extractive_summary_and_user_approved_memory_persist(isolated_ai_store):
    conversation_id = "conversation-a"
    messages = [
        {"id": i, "role": "user" if i % 2 else "assistant", "content": f"message {i}"}
        for i in range(1, 8)
    ]
    summary = store.update_extractive_summary(conversation_id, messages, keep_recent=2)
    assert "message 1" in summary and "message 5" in summary
    assert store.update_extractive_summary(
        conversation_id, messages, keep_recent=2
    ) == summary

    memory_id = store.add_memory("User prefers concise answers.")
    assert store.list_memories()[0]["id"] == memory_id
    assert store.search_memories("concise answers")
    store.add_memory("User prefers brief replies.", memory_id)
    assert "brief replies" in store.list_memories()[0]["content"]
    store.delete_memory(memory_id)
    assert store.list_memories() == []


def test_usage_dashboard_counts_requests_attempts_and_cache_savings(
    isolated_ai_store,
):
    store.record_usage("request-a", "gemini", "flash", "failed")
    store.record_usage("request-a", "openrouter", "free", "success", 20, 15)
    store.record_usage(
        "request-b", "gemini", "flash", "cache", 20, 15, cache_hit=True
    )

    assert store.usage_stats() == {
        "requests": 2,
        "attempts": 3,
        "input_tokens": 40,
        "output_tokens": 30,
        "cache_hits": 1,
        "failures": 1,
        "estimated_saved_tokens": 35,
    }


def test_ai_pipeline_provider_model_selection_persists(isolated_ai_store, qtbot):
    from jarvis.ui.ai_pipeline_dialog import AIPipelineDialog

    settings = Settings(ai_cache_enabled=False)
    dialog = AIPipelineDialog(settings)
    qtbot.addWidget(dialog)
    dialog.provider.setCurrentIndex(dialog.provider.findData("grok"))
    dialog.model.setEditText("grok-test-model")
    dialog._save()

    assert settings.get("ai_primary_provider") == "grok"
    assert settings.get("ai_primary_model") == "grok-test-model"
    assert settings.saves == 1
    dialog.close()


def test_add_credential_uses_password_echo_mode(monkeypatch, qtbot):
    from PySide6.QtWidgets import QInputDialog, QLineEdit, QListWidget
    from jarvis.ui.ai_pipeline_dialog import AIPipelineDialog

    class MemoryCredentialStore:
        def __init__(self):
            self.saved = {}

        def set(self, credential_id, secret):
            self.saved[credential_id] = secret

    calls = []
    answers = iter([
        ("Gemini", True),
        ("Personal key", True),
        ("project-123", True),
        ("private-key-test", True),
    ])

    def get_item(*_args, **_kwargs):
        return next(answers)

    def get_text(*args, **_kwargs):
        calls.append(args)
        return next(answers)

    monkeypatch.setattr(QInputDialog, "getItem", get_item)
    monkeypatch.setattr(QInputDialog, "getText", get_text)

    settings = Settings()
    dialog = AIPipelineDialog(settings)
    qtbot.addWidget(dialog)
    credential_store = MemoryCredentialStore()
    dialog._credential_store = credential_store
    listing = QListWidget()

    dialog._add_credential(listing)

    assert calls[-1][3] == QLineEdit.EchoMode.Password
    assert credential_store.saved == {
        settings.get("ai_credentials")[0]["id"]: "private-key-test"
    }
    assert "priv" not in listing.item(0).text()
    dialog.close()
