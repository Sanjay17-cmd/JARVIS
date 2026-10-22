from __future__ import annotations

import json
from urllib.error import HTTPError

import pytest

from jarvis.ai.web_search import (
    WebSearchError, WebSearchService, search_statistics,
)
from jarvis.scheduling import database


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    database.close()
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(database, "_db_path", lambda: tmp_path / "search.db")
    database._conn = None
    yield
    database.close()
    database._conn = None


class Settings:
    def __init__(self, **values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)


class Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size=-1):
        return self.payload if size < 0 else self.payload[:size]


def test_brave_search_returns_normalized_source_and_caches_request():
    calls = []

    def opener(request, timeout):
        calls.append((request, timeout))
        return Response({
            "web": {
                "results": [{
                    "title": "Python release",
                    "url": "https://www.python.org/downloads/",
                    "description": "Release details",
                    "page_age": "2026-10-20T00:00:00Z",
                }]
            }
        })

    service = WebSearchService(Settings(search_cache_ttl_minutes=30), opener)

    first = service.search("latest Python release", "brave", "secret")
    second = service.search("latest  Python release", "brave", "secret")

    assert first.results[0].title == "Python release"
    assert first.results[0].published_date == "2026-10-20T00:00:00Z"
    assert second.cache_hit is True
    assert len(calls) == 1
    assert calls[0][0].get_header("X-subscription-token") == "secret"
    assert "count=5" in calls[0][0].full_url


def test_tavily_search_uses_documented_post_body_and_auth():
    captured = {}

    def opener(request, timeout):
        captured["request"] = request
        captured["body"] = json.loads(request.data)
        return Response({
            "results": [{
                "title": "Python news",
                "url": "https://example.com/python",
                "content": "New release information.",
                "published_date": "2026-10-21",
            }]
        })

    result = WebSearchService(opener=opener).search(
        "latest Python news", "tavily", "tavily-secret"
    )

    assert captured["request"].get_header("Authorization") == "Bearer tavily-secret"
    assert captured["body"]["search_depth"] == "basic"
    assert captured["body"]["topic"] == "news"
    assert captured["body"]["include_published_date"] is True
    assert result.results[0].published_date == "2026-10-21"


def test_openrouter_search_requires_model_and_normalizes_citations():
    captured = {}

    def opener(request, timeout):
        captured["body"] = json.loads(request.data)
        return Response({
            "choices": [{
                "message": {
                    "content": "Search summary",
                    "annotations": [{
                        "type": "url_citation",
                        "url_citation": {
                            "title": "Source",
                            "url": "https://example.com/source",
                            "content": "Evidence",
                        },
                    }],
                }
            }]
        })

    service = WebSearchService(opener=opener)
    with pytest.raises(WebSearchError, match="Select an OpenRouter model"):
        service.search("query", "openrouter", "key")

    result = service.search(
        "query", "openrouter", "key", model="openrouter/test"
    )
    assert captured["body"]["tools"] == [{"type": "openrouter:web_search"}]
    assert result.answer == "Search summary"
    assert result.results[0].url == "https://example.com/source"


def test_search_rejects_empty_and_does_not_fabricate_on_provider_error():
    def failed(_request, **_kwargs):
        raise HTTPError(
            "https://api.search.brave.com",
            429,
            "rate limited",
            {},
            None,
        )

    service = WebSearchService(opener=failed)
    with pytest.raises(WebSearchError, match="Enter a search query"):
        service.search(" ", "brave", "key")
    with pytest.raises(WebSearchError, match="rate limit"):
        service.search("news", "brave", "key")


def test_cancelled_search_does_not_call_provider():
    from threading import Event

    calls = []
    service = WebSearchService(
        opener=lambda *_args, **_kwargs: calls.append(True)
    )
    cancelled = Event()
    cancelled.set()

    with pytest.raises(WebSearchError, match="cancelled"):
        service.search("query", "brave", "key", cancel_event=cancelled)
    assert calls == []


def test_invalid_and_duplicate_source_urls_are_removed():
    results = WebSearchService._normalize_results(
        [
            {"title": "bad", "url": "file:///secret", "snippet": "no"},
            {
                "title": "Source",
                "url": "https://example.com",
                "snippet": "evidence",
            },
            {
                "title": "Duplicate",
                "url": "https://example.com",
                "snippet": "same source",
            },
        ],
        5,
    )

    assert len(results) == 1
    assert results[0].url == "https://example.com"


def test_generated_search_summary_cache_round_trip():
    service = WebSearchService(Settings(search_cache_ttl_minutes=10))

    assert service.get_cached_answer("query-context-key") is None
    service.save_cached_answer("query-context-key", "Verified summary")

    assert service.get_cached_answer("query-context-key") == "Verified summary"
    assert search_statistics()["requests"] == 0
