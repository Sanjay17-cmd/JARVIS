import json

from jarvis.ai.provider import GeminiProvider, get_provider


class _Settings:
    def __init__(self, values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)


def test_gemini_uses_configured_environment_key_and_returns_text(monkeypatch):
    monkeypatch.setenv("TEST_GEMINI_KEY", "fake-test-key")
    captured = {}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps({
                "candidates": [{
                    "content": {"parts": [{"text": "Gemini answer"}]}
                }]
            }).encode()

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = GeminiProvider(
        model="gemini-test-model",
        timeout=7,
        api_key_env_var="TEST_GEMINI_KEY",
    )

    assert provider.ask("test prompt") == "Gemini answer"
    request = captured["request"]
    assert request.get_header("X-goog-api-key") == "fake-test-key"
    assert "fake-test-key" not in request.full_url
    assert captured["timeout"] == 7


def test_gemini_missing_key_reports_setup_without_network(monkeypatch):
    monkeypatch.delenv("TEST_GEMINI_KEY", raising=False)
    provider = GeminiProvider(api_key_env_var="TEST_GEMINI_KEY")
    result = provider.ask("hello")
    assert "TEST_GEMINI_KEY" in result
    assert "unavailable" in result.lower()


def test_provider_factory_selects_gemini():
    provider = get_provider(_Settings({
        "ai_provider": "gemini",
        "ai_model": "gemini-custom",
        "ai_timeout": 17,
        "ai_api_key_env_var": "MY_GEMINI_KEY",
    }))
    assert provider.name == "gemini/gemini-custom"
