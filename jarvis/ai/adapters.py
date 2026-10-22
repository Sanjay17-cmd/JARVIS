"""Provider-specific HTTP adapters behind a common text-generation interface."""
from __future__ import annotations

import json
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from threading import Event


class RequestCancelled(Exception):
    pass


class ProviderError(RuntimeError):
    def __init__(
        self,
        provider: str,
        category: str,
        message: str,
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.category = category
        self.status_code = status_code
        self.retry_after = retry_after


@dataclass(frozen=True)
class GenerationResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0


def _retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            return max(0.0, parsedate_to_datetime(value).timestamp() - time.time())
        except (TypeError, ValueError, OverflowError):
            return None


def _classify_error(provider: str, status: int, message: str) -> str:
    text = message.casefold()
    if status in {401, 403}:
        return "invalid_auth"
    if status == 402 or any(term in text for term in ("insufficient credit", "billing balance", "payment required")):
        return "insufficient_credits"
    if status == 429:
        if any(term in text for term in (
            "daily quota", "quota exceeded", "exceeded your current quota",
            "resource_exhausted", "per day", "free_tier",
        )):
            return "quota_exhausted"
        return "rate_limit"
    if status in {400, 404} and any(
        term in text for term in (
            "model not found", "unsupported model", "no endpoints found",
            "model does not exist", "model unavailable",
        )
    ):
        return "unsupported_model"
    if status in {400, 422}:
        return "invalid_request"
    if status >= 500:
        return "transient"
    return "provider_unavailable"


def _error_detail(payload, default: str) -> str:
    if not isinstance(payload, dict):
        return default
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error.get("type") or default)
    return str(error) if error else default


class ProviderAdapter:
    provider_id = ""

    def generate(
        self,
        model: str,
        system_prompt: str,
        messages: list[dict[str, str]],
        api_key: str,
        max_output_tokens: int,
        timeout: int,
        cancel_event: Event,
    ) -> GenerationResult:
        raise NotImplementedError

    def list_models(self, api_key: str, timeout: int) -> list[dict]:
        raise NotImplementedError

    def _request_events(
        self,
        url: str,
        api_key: str,
        timeout: int,
        body: dict,
        headers: dict[str, str] | None = None,
        cancel_event: Event | None = None,
    ):
        request_headers = dict(headers or {})
        if api_key and self.provider_id != "gemini":
            request_headers["Authorization"] = f"Bearer {api_key}"
        request_headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers=request_headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                for raw_line in response:
                    if cancel_event and cancel_event.is_set():
                        raise RequestCancelled()
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        yield json.loads(data)
                    except json.JSONDecodeError:
                        continue
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode("utf-8", errors="replace"))
                detail = _error_detail(payload, "Provider rejected the request.")
            except (ValueError, OSError):
                detail = "Provider rejected the request."
            detail = str(detail).replace(api_key, "[redacted]") if api_key else str(detail)
            raise ProviderError(
                self.provider_id,
                _classify_error(self.provider_id, exc.code, detail),
                f"{self.provider_id} HTTP {exc.code}: {detail}",
                status_code=exc.code,
                retry_after=_retry_after((exc.headers or {}).get("Retry-After")),
            ) from None
        except urllib.error.URLError as exc:
            category = "timeout" if isinstance(exc.reason, (TimeoutError, socket.timeout)) else "network"
            raise ProviderError(self.provider_id, category, f"{self.provider_id} network error ({category}).") from None
        except (TimeoutError, socket.timeout):
            raise ProviderError(self.provider_id, "timeout", f"{self.provider_id} request timed out.") from None

    def _request_json(
        self,
        url: str,
        api_key: str,
        timeout: int,
        body: dict | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict:
        headers = dict(extra_headers or {})
        if api_key and self.provider_id != "gemini":
            headers["Authorization"] = f"Bearer {api_key}"
        data = None if body is None else json.dumps(body).encode("utf-8")
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="replace")
                payload = json.loads(detail)
                detail = _error_detail(payload, "Provider rejected the request.")
            except (ValueError, OSError):
                detail = "Provider rejected the request."
            detail = str(detail).replace(api_key, "[redacted]") if api_key else str(detail)
            raise ProviderError(
                self.provider_id,
                _classify_error(self.provider_id, exc.code, detail),
                f"{self.provider_id} HTTP {exc.code}: {detail}",
                status_code=exc.code,
                retry_after=_retry_after((exc.headers or {}).get("Retry-After")),
            ) from None
        except urllib.error.URLError as exc:
            reason = exc.reason
            category = "timeout" if isinstance(reason, (TimeoutError, socket.timeout)) else "network"
            raise ProviderError(
                self.provider_id, category,
                f"{self.provider_id} network error ({category}).",
            ) from None
        except (TimeoutError, socket.timeout):
            raise ProviderError(
                self.provider_id, "timeout", f"{self.provider_id} request timed out."
            ) from None
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ProviderError(
                self.provider_id, "invalid_response",
                f"{self.provider_id} returned invalid JSON.",
            ) from None


class GeminiAdapter(ProviderAdapter):
    provider_id = "gemini"
    _base = "https://generativelanguage.googleapis.com/v1beta"

    def list_models(self, api_key: str, timeout: int) -> list[dict]:
        result = self._request_json(
            f"{self._base}/models?pageSize=1000",
            api_key,
            timeout,
            extra_headers={"x-goog-api-key": api_key},
        )
        models = []
        for item in result.get("models", []):
            methods = item.get("supportedGenerationMethods", [])
            if "generateContent" not in methods:
                continue
            model_id = str(item.get("name", "")).removeprefix("models/")
            if re.search(
                r"(tts|audio|live|transcrib|image|embedding|veo|video)",
                model_id,
                re.IGNORECASE,
            ):
                continue
            if model_id:
                models.append({
                    "id": model_id,
                    "name": item.get("displayName", model_id),
                    "free": False,
                    "input_tokens": item.get("inputTokenLimit", 0),
                    "output_tokens": item.get("outputTokenLimit", 0),
                })
        def model_order(item):
            model_id = item["id"].casefold()
            preview = bool(re.search(r"(preview|experimental|exp)", model_id))
            version = tuple(
                -int(part) for part in re.findall(r"\d+", model_id)
            )
            return preview, version, item["name"].casefold()

        return sorted(models, key=model_order)

    def generate(self, model, system_prompt, messages, api_key, max_output_tokens,
                 timeout, cancel_event, on_chunk=None) -> GenerationResult:
        contents = []
        for message in messages:
            contents.append({
                "role": "model" if message["role"] == "assistant" else "user",
                "parts": [{"text": message["content"]}],
            })
        body = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": max_output_tokens,
                "temperature": 0.0,
            },
        }
        if on_chunk is None:
            result = self._request_json(
                f"{self._base}/models/{urllib.parse.quote(model, safe='')}:generateContent",
                api_key,
                timeout,
                body,
                {"x-goog-api-key": api_key},
            )
            events = [result]
        else:
            events = self._request_events(
                f"{self._base}/models/{urllib.parse.quote(model, safe='')}:streamGenerateContent?alt=sse",
                api_key,
                timeout,
                body,
                {"x-goog-api-key": api_key},
                cancel_event,
            )
        text_parts = []
        usage = {}
        for event in events:
            try:
                parts = event["candidates"][0]["content"]["parts"]
            except (KeyError, IndexError, TypeError):
                parts = []
            chunk = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
            if chunk:
                text_parts.append(chunk)
                if on_chunk:
                    on_chunk(chunk)
            usage.update(event.get("usageMetadata", {}))
        text = "".join(text_parts).strip()
        if not text:
            raise ProviderError(self.provider_id, "invalid_response", "Gemini returned no text.")
        return GenerationResult(
            text,
            int(usage.get("promptTokenCount", 0)),
            int(usage.get("candidatesTokenCount", 0)),
        )


class OpenRouterAdapter(ProviderAdapter):
    provider_id = "openrouter"
    _base = "https://openrouter.ai/api/v1"

    def list_models(self, api_key: str, timeout: int) -> list[dict]:
        result = self._request_json(f"{self._base}/models", api_key, timeout)
        from jarvis.ai.free_models import is_verified_free_model

        models = []
        for item in result.get("data", []):
            model_id = str(item.get("id", ""))
            if model_id:
                free = is_verified_free_model(item, "text")
                models.append({
                    "id": model_id,
                    "name": item.get("name", model_id),
                    "free": free,
                    "input_tokens": item.get("context_length", 0),
                })
        return sorted(models, key=lambda item: (not item["free"], item["name"].casefold()))

    def generate(self, model, system_prompt, messages, api_key, max_output_tokens,
                 timeout, cancel_event, on_chunk=None) -> GenerationResult:
        payload_messages = [{"role": "system", "content": system_prompt}]
        payload_messages.extend(messages)
        result = _openai_compatible_generation(
            self, f"{self._base}/chat/completions", model, payload_messages,
            api_key, max_output_tokens, timeout, cancel_event, on_chunk,
        )
        return result


class GrokAdapter(ProviderAdapter):
    provider_id = "grok"
    _base = "https://api.x.ai/v1"

    def list_models(self, api_key: str, timeout: int) -> list[dict]:
        result = self._request_json(f"{self._base}/models", api_key, timeout)
        return sorted(
            [
                {"id": str(item["id"]), "name": str(item.get("id")),"free": False}
                for item in result.get("data", [])
                if item.get("id")
            ],
            key=lambda item: item["id"].casefold(),
        )

    def generate(self, model, system_prompt, messages, api_key, max_output_tokens,
                 timeout, cancel_event, on_chunk=None) -> GenerationResult:
        payload_messages = [{"role": "system", "content": system_prompt}]
        payload_messages.extend(messages)
        return _openai_compatible_generation(
            self, f"{self._base}/chat/completions", model, payload_messages,
            api_key, max_output_tokens, timeout, cancel_event, on_chunk,
        )


class OpenAIAdapter(OpenRouterAdapter):
    """Compatibility adapter for existing OpenAI configurations."""

    provider_id = "openai"
    _base = "https://api.openai.com/v1"


class GroqAdapter(OpenAIAdapter):
    """GroqCloud's OpenAI-compatible chat completions API."""

    provider_id = "groq"
    _base = "https://api.groq.com/openai/v1"


def _openai_compatible_generation(
    adapter: ProviderAdapter,
    url: str,
    model: str,
    messages: list[dict[str, str]],
    api_key: str,
    max_output_tokens: int,
    timeout: int,
    cancel_event: Event,
    on_chunk=None,
) -> GenerationResult:
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_output_tokens,
        "temperature": 0.0,
        "stream": on_chunk is not None,
    }
    if on_chunk is None:
        result = adapter._request_json(url, api_key, timeout, payload)
        events = [result]
    else:
        events = adapter._request_events(url, api_key, timeout, payload, cancel_event=cancel_event)
    text_parts = []
    usage = {}
    for event in events:
        try:
            choice = event["choices"][0]
            chunk = (
                choice.get("delta", {}).get("content", "")
                if on_chunk is not None
                else choice.get("message", {}).get("content", "")
            )
        except (KeyError, IndexError, TypeError):
            chunk = ""
        if isinstance(chunk, list):
            chunk = "".join(str(part.get("text", "")) for part in chunk if isinstance(part, dict))
        if chunk:
            text_parts.append(str(chunk))
            if on_chunk:
                on_chunk(str(chunk))
        usage.update(event.get("usage", {}))
    text = "".join(text_parts).strip()
    if not text:
        raise ProviderError(adapter.provider_id, "invalid_response", "Provider returned no text.")
    return GenerationResult(
        text,
        int(usage.get("prompt_tokens", 0)),
        int(usage.get("completion_tokens", 0)),
    )


ADAPTERS: dict[str, ProviderAdapter] = {
    "gemini": GeminiAdapter(),
    "openrouter": OpenRouterAdapter(),
    "grok": GrokAdapter(),
    "openai": OpenAIAdapter(),
    "groq": GroqAdapter(),
}
