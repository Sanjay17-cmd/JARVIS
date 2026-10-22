"""Independent web-search providers, result cache, and privacy-safe statistics."""
from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import time
from dataclasses import dataclass
from threading import Event
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from jarvis.scheduling import database

log = logging.getLogger(__name__)

_SEARCH_URLS = {
    "brave": "https://api.search.brave.com/res/v1/web/search",
    "tavily": "https://api.tavily.com/search",
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
}
_NEWS_QUERY = re.compile(
    r"\b(news|breaking|latest|today|current|recent|this week|release)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    published_date: str = ""


@dataclass(frozen=True)
class SearchResponse:
    provider: str
    query: str
    results: tuple[SearchResult, ...]
    answer: str = ""
    cache_hit: bool = False
    cache_key: str = ""


class WebSearchError(RuntimeError):
    """Search failed or was not configured; never represents fabricated results."""


def _initialize() -> None:
    with database._lock:
        conn = database.get_conn()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS web_search_cache (
                cache_key TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                query_hash TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_web_search_cache_expiry
                ON web_search_cache(expires_at);
            CREATE TABLE IF NOT EXISTS web_search_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL,
                cache_hit INTEGER NOT NULL DEFAULT 0,
                success INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS web_search_answer_cache (
                answer_key TEXT PRIMARY KEY,
                answer TEXT NOT NULL,
                expires_at REAL NOT NULL
            );
            """
        )
        conn.commit()


def search_statistics(provider: str | None = None) -> dict[str, int]:
    _initialize()
    query = (
        "SELECT COUNT(*) AS requests, "
        "COALESCE(SUM(cache_hit),0) AS cache_hits, "
        "COALESCE(SUM(CASE WHEN success=0 THEN 1 ELSE 0 END),0) AS failures "
        "FROM web_search_usage"
    )
    row = (
        database.execute(query + " WHERE provider=?", (provider,)).fetchone()
        if provider else database.execute(query).fetchone()
    )
    return {key: int(row[key]) for key in ("requests", "cache_hits", "failures")}


class WebSearchService:
    def __init__(self, settings=None, opener=urlopen) -> None:
        self._settings = settings
        self._opener = opener

    def search(
        self,
        query: str,
        provider: str,
        api_key: str,
        *,
        model: str = "",
        timeout: int = 12,
        max_results: int = 5,
        cancel_event: Event | None = None,
    ) -> SearchResponse:
        query = " ".join(query.split())
        if not query:
            raise WebSearchError("Enter a search query.")
        if len(query) > 500:
            raise WebSearchError("Search query must be 500 characters or fewer.")
        if cancel_event is not None and cancel_event.is_set():
            raise WebSearchError("Search request cancelled.")
        if provider not in _SEARCH_URLS:
            raise WebSearchError(f"Unsupported search provider: {provider}.")
        if not api_key.strip():
            raise WebSearchError(
                f"No secure API key is configured for {provider}. "
                "Add one in Settings → Web Search."
            )
        max_results = max(1, min(int(max_results), 5))
        timeout = max(1, min(int(timeout), 30))
        query_hash = hashlib.sha256(query.casefold().encode("utf-8")).hexdigest()
        cache_key = hashlib.sha256(
            f"{provider}\0{model}\0{query_hash}".encode("utf-8")
        ).hexdigest()
        _initialize()
        now = time.time()
        cached = database.execute(
            "SELECT payload FROM web_search_cache "
            "WHERE cache_key=? AND expires_at>?",
            (cache_key, now),
        ).fetchone()
        if cached:
            response = self._deserialize(
                provider, query, cached["payload"], True, cache_key
            )
            self._record(provider, cache_hit=True, success=True)
            return response

        try:
            if provider == "brave":
                results, answer = self._search_brave(
                    query, api_key, timeout, max_results
                )
            elif provider == "tavily":
                results, answer = self._search_tavily(
                    query, api_key, timeout, max_results
                )
            else:
                results, answer = self._search_openrouter(
                    query, api_key, model, timeout, max_results
                )
            if cancel_event is not None and cancel_event.is_set():
                raise WebSearchError("Search request cancelled.")
            if not results:
                raise WebSearchError(
                    f"{provider} returned no verifiable web results for this query."
                )
            payload = json.dumps(
                {
                    "results": [result.__dict__ for result in results],
                    "answer": answer,
                },
                ensure_ascii=False,
            )
            default_ttl = 15 if _NEWS_QUERY.search(query) else 240
            ttl_key = (
                "search_news_cache_ttl_minutes"
                if _NEWS_QUERY.search(query)
                else "search_cache_ttl_minutes"
            )
            ttl_minutes = int(
                self._settings.get(ttl_key, default_ttl)
                if self._settings is not None else default_ttl
            )
            ttl = max(1, min(ttl_minutes, 30 * 24 * 60)) * 60
            with database._lock:
                database.get_conn().execute(
                    "INSERT OR REPLACE INTO web_search_cache "
                    "(cache_key,provider,query_hash,payload,created_at,expires_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (cache_key, provider, query_hash, payload, now, now + ttl),
                )
                database.get_conn().execute(
                    "DELETE FROM web_search_cache WHERE expires_at<=?", (now,)
                )
                database.get_conn().commit()
            self._record(provider, cache_hit=False, success=True)
            return SearchResponse(
                provider, query, tuple(results), answer, False, cache_key
            )
        except Exception as exc:
            self._record(provider, cache_hit=False, success=False)
            if isinstance(exc, WebSearchError):
                raise
            if isinstance(exc, HTTPError):
                if exc.code == 401 or exc.code == 403:
                    detail = "API key was rejected or lacks search access."
                elif exc.code == 429:
                    detail = "Provider rate limit reached; try again later."
                else:
                    detail = f"Provider returned HTTP {exc.code}."
                raise WebSearchError(f"{provider} search failed: {detail}") from exc
            if isinstance(exc, (TimeoutError, URLError)):
                raise WebSearchError(
                    f"{provider} search could not connect or timed out."
                ) from exc
            log.exception("Web search failed for provider=%s", provider)
            raise WebSearchError(f"{provider} search failed: {exc}") from exc

    def _request_json(
        self, url: str, api_key: str, provider: str, timeout: int,
        *, body: dict | None = None,
    ) -> dict:
        headers = {"Accept": "application/json"}
        data = None
        if provider == "brave":
            headers["X-Subscription-Token"] = api_key
        else:
            headers["Authorization"] = f"Bearer {api_key}"
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")
        request = Request(url, data=data, headers=headers)
        with self._opener(request, timeout=timeout) as response:
            raw_payload = response.read(2_000_001)
        if len(raw_payload) > 2_000_000:
            raise WebSearchError(f"{provider} response exceeded the size limit.")
        payload = json.loads(raw_payload.decode("utf-8"))
        if not isinstance(payload, dict):
            raise WebSearchError(f"{provider} returned an invalid response.")
        return payload

    def _search_brave(self, query, api_key, timeout, max_results):
        url = _SEARCH_URLS["brave"] + "?" + urlencode(
            {"q": query, "count": max_results, "safesearch": "moderate"}
        )
        data = self._request_json(url, api_key, "brave", timeout)
        raw_results = data.get("web", {}).get("results", [])
        return self._normalize_results(
            (
                {
                    "title": item.get("title"),
                    "url": item.get("url"),
                    "snippet": item.get("description"),
                    "published_date": item.get("page_age"),
                }
                for item in raw_results
            ),
            max_results,
        ), ""

    def _search_tavily(self, query, api_key, timeout, max_results):
        topic = "news" if _NEWS_QUERY.search(query) else "general"
        data = self._request_json(
            _SEARCH_URLS["tavily"],
            api_key,
            "tavily",
            timeout,
            body={
                "query": query,
                "search_depth": "basic",
                "topic": topic,
                "max_results": max_results,
                "include_answer": False,
                "include_raw_content": False,
                "include_published_date": True,
            },
        )
        return self._normalize_results(
            (
                {
                    "title": item.get("title"),
                    "url": item.get("url"),
                    "snippet": item.get("content"),
                    "published_date": item.get("published_date") or "",
                }
                for item in data.get("results", [])
            ),
            max_results,
        ), ""

    def _search_openrouter(self, query, api_key, model, timeout, max_results):
        if not model:
            raise WebSearchError(
                "Select an OpenRouter model to use OpenRouter web search."
            )
        data = self._request_json(
            _SEARCH_URLS["openrouter"],
            api_key,
            "openrouter",
            timeout,
            body={
                "model": model,
                "messages": [{"role": "user", "content": query}],
                "tools": [{"type": "openrouter:web_search"}],
                "web_search_options": {
                    "max_results": max_results,
                    "search_context_size": "low",
                },
            },
        )
        choices = data.get("choices", [])
        if not choices:
            return [], ""
        message = choices[0].get("message", {})
        annotations = message.get("annotations", [])
        results = self._normalize_results(
            (
                {
                    "title": item.get("url_citation", {}).get("title"),
                    "url": item.get("url_citation", {}).get("url"),
                    "snippet": item.get("url_citation", {}).get("content", ""),
                    "published_date": "",
                }
                for item in annotations
                if item.get("type") == "url_citation"
            ),
            max_results,
        )
        answer = message.get("content", "")
        if isinstance(answer, list):
            answer = " ".join(
                str(item.get("text", "")) for item in answer
                if isinstance(item, dict)
            )
        return results, str(answer)

    @staticmethod
    def _normalize_results(items, limit: int) -> list[SearchResult]:
        results: list[SearchResult] = []
        seen: set[str] = set()
        for item in items:
            url = str(item.get("url") or "").strip()
            if not url.startswith(("https://", "http://")) or url in seen:
                continue
            title = " ".join(str(item.get("title") or "").split())[:240]
            snippet = " ".join(str(item.get("snippet") or "").split())[:900]
            if not title:
                continue
            seen.add(url)
            results.append(
                SearchResult(
                    title,
                    url,
                    snippet,
                    str(item.get("published_date") or "")[:64],
                )
            )
            if len(results) >= limit:
                break
        return results

    @staticmethod
    def _deserialize(
        provider: str,
        query: str,
        payload: str,
        cache_hit: bool,
        cache_key: str,
    ):
        data = json.loads(payload)
        results = tuple(SearchResult(**item) for item in data["results"])
        return SearchResponse(
            provider, query, results, str(data.get("answer", "")),
            cache_hit, cache_key
        )

    def get_cached_answer(self, answer_key: str) -> str | None:
        _initialize()
        row = database.execute(
            "SELECT answer FROM web_search_answer_cache "
            "WHERE answer_key=? AND expires_at>?",
            (answer_key, time.time()),
        ).fetchone()
        return str(row["answer"]) if row else None

    def save_cached_answer(
        self, answer_key: str, answer: str, news: bool = False
    ) -> None:
        _initialize()
        ttl_key = (
            "search_news_cache_ttl_minutes" if news
            else "search_cache_ttl_minutes"
        )
        default_ttl = 15 if news else 240
        ttl_minutes = int(
            self._settings.get(ttl_key, default_ttl)
            if self._settings is not None else default_ttl
        )
        ttl = max(1, min(ttl_minutes, 30 * 24 * 60)) * 60
        with database._lock:
            database.get_conn().execute(
                "INSERT OR REPLACE INTO web_search_answer_cache "
                "(answer_key,answer,expires_at) VALUES (?,?,?)",
                (answer_key, answer, time.time() + ttl),
            )
            database.get_conn().execute(
                "DELETE FROM web_search_answer_cache WHERE expires_at<=?",
                (time.time(),),
            )
            database.get_conn().commit()

    @staticmethod
    def _record(provider: str, cache_hit: bool, success: bool) -> None:
        with database._lock:
            database.get_conn().execute(
                "INSERT INTO web_search_usage(provider,cache_hit,success,created_at) "
                "VALUES (?,?,?,?)",
                (provider, int(cache_hit), int(success), time.time()),
            )
            database.get_conn().commit()
