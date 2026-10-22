"""Free-tier image generation for OpenRouter and Gemini-compatible models."""
from __future__ import annotations

import base64
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from threading import Event

from jarvis.ai.free_models import (
    FreeModelCatalogError,
    list_free_openrouter_models,
)


_GEMINI_FREE_IMAGE_MODELS = {
    "gemini-2.0-flash-preview-image-generation",
    "gemini-2.5-flash-image-preview",
    "gemini-2.0-flash-exp-image-generation",
    "imagen-3.0-generate-002",
    "imagen-3.0-generate-001",
}


class ImageGenerationError(RuntimeError):
    pass


@dataclass(frozen=True)
class GeneratedImage:
    content: bytes
    media_type: str
    cost_usd: float | None = None


def provider_for_image_model(model: str) -> str:
    normalized = (model or "").strip().lower()
    if not normalized:
        return "openrouter"
    if normalized.startswith("gemini-") or normalized.startswith("imagen-"):
        return "gemini"
    return "openrouter"


def is_gemini_free_image_model(model: str) -> bool:
    normalized = (model or "").strip().lower()
    if not normalized:
        return False
    if normalized in _GEMINI_FREE_IMAGE_MODELS:
        return True
    return (
        normalized.startswith("gemini-")
        or normalized.startswith("imagen-")
    ) and (
        "image" in normalized
        or "preview" in normalized
        or "generate" in normalized
    )


def list_free_image_models(*, timeout: int = 15) -> list[dict[str, str]]:
    """Return zero-cost image models currently allowed by the app."""
    models: list[dict[str, str]] = []
    try:
        models.extend(list_free_openrouter_models("image", timeout=timeout))
    except FreeModelCatalogError as exc:
        raise ImageGenerationError(str(exc)) from exc

    for model_id in sorted(_GEMINI_FREE_IMAGE_MODELS):
        models.append({"id": model_id, "name": model_id, "free": True})

    seen: set[str] = set()
    ordered: list[dict[str, str]] = []
    for item in sorted(models, key=lambda entry: entry["name"].casefold()):
        model_id = item["id"]
        if model_id in seen:
            continue
        seen.add(model_id)
        ordered.append({"id": model_id, "name": item["name"], "free": True})
    return ordered


def generate_image(
    prompt: str,
    api_key: str,
    model: str,
    *,
    timeout: int = 120,
    cancel_event: Event | None = None,
) -> GeneratedImage:
    prompt = prompt.strip()
    model = model.strip()
    if not prompt:
        raise ImageGenerationError("Enter an image description first.")
    if not api_key:
        raise ImageGenerationError(
            "No provider API key is configured. Add a valid Gemini or OpenRouter key in AI Pipeline Settings."
        )
    if not model:
        raise ImageGenerationError("Enter an image model ID.")
    if cancel_event is not None and cancel_event.is_set():
        raise ImageGenerationError("Image generation was cancelled.")

    provider = provider_for_image_model(model)
    free_models = list_free_image_models(timeout=min(timeout, 30))
    allowed = {item["id"] for item in free_models}
    if provider == "gemini":
        if not is_gemini_free_image_model(model):
            raise ImageGenerationError(
                f"'{model}' is not a known free Gemini image model. No image request was sent."
            )
        if model not in allowed:
            allowed.add(model)
    elif model not in allowed:
        raise ImageGenerationError(
            f"'{model}' is not currently listed by OpenRouter as a zero-priced image model. No image request was sent."
        )

    if cancel_event is not None and cancel_event.is_set():
        raise ImageGenerationError("Image generation was cancelled.")

    if provider == "gemini":
        return _generate_gemini_image(model, prompt, api_key, timeout, cancel_event)

    return _generate_openrouter_image(model, prompt, api_key, timeout, cancel_event)


def _generate_openrouter_image(
    model: str,
    prompt: str,
    api_key: str,
    timeout: int,
    cancel_event: Event | None,
) -> GeneratedImage:
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/images",
        data=json.dumps({"model": model, "prompt": prompt}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            details = json.loads(exc.read().decode("utf-8", errors="replace"))
            error = details.get("error", {}) if isinstance(details, dict) else {}
            message = (
                error.get("message", "OpenRouter rejected the image request.")
                if isinstance(error, dict)
                else str(error)
            )
        except (ValueError, OSError):
            message = "OpenRouter rejected the image request."
        message = str(message).replace(api_key, "[redacted]")
        raise ImageGenerationError(
            f"OpenRouter image request failed (HTTP {exc.code}): {message}"
        ) from None
    except urllib.error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, (TimeoutError, socket.timeout)):
            message = "OpenRouter image request timed out."
        else:
            message = "Could not connect to OpenRouter for image generation."
        raise ImageGenerationError(message) from None
    except (TimeoutError, socket.timeout):
        raise ImageGenerationError("OpenRouter image request timed out.") from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ImageGenerationError("OpenRouter returned an invalid image response.") from None

    if cancel_event is not None and cancel_event.is_set():
        raise ImageGenerationError("Image generation was cancelled.")
    if not isinstance(payload, dict):
        raise ImageGenerationError("OpenRouter returned an invalid image response.")
    images = payload.get("data")
    if not isinstance(images, list) or not images or not isinstance(images[0], dict):
        raise ImageGenerationError("OpenRouter returned no image data.")
    encoded = images[0].get("b64_json")
    if not isinstance(encoded, str) or not encoded:
        raise ImageGenerationError("OpenRouter's image response contained no image bytes.")
    try:
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, base64.binascii.Error):
        raise ImageGenerationError("OpenRouter returned invalid base64 image data.") from None
    if not content:
        raise ImageGenerationError("OpenRouter returned an empty image.")

    media_type = str(images[0].get("media_type") or "image/png").lower()
    usage = payload.get("usage")
    cost = usage.get("cost") if isinstance(usage, dict) else None
    try:
        cost_usd = float(cost) if cost is not None else None
    except (TypeError, ValueError):
        cost_usd = None
    return GeneratedImage(content, media_type, cost_usd)


def _generate_gemini_image(
    model: str,
    prompt: str,
    api_key: str,
    timeout: int,
    cancel_event: Event | None,
) -> GeneratedImage:
    request = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{urllib.parse.quote(model, safe='')}:generateContent",
        data=json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseModalities": ["TEXT", "IMAGE"],
            },
        }).encode("utf-8"),
        headers={
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            details = json.loads(exc.read().decode("utf-8", errors="replace"))
            message = details.get("error", {}).get("message", "Gemini rejected the image request.") if isinstance(details, dict) else "Gemini rejected the image request."
        except (ValueError, OSError):
            message = "Gemini rejected the image request."
        raise ImageGenerationError(f"Gemini image request failed: {message}") from None
    except urllib.error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, (TimeoutError, socket.timeout)):
            message = "Gemini image request timed out."
        else:
            message = "Could not connect to Gemini for image generation."
        raise ImageGenerationError(message) from None
    except (TimeoutError, socket.timeout):
        raise ImageGenerationError("Gemini image request timed out.") from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ImageGenerationError("Gemini returned an invalid image response.") from None

    if cancel_event is not None and cancel_event.is_set():
        raise ImageGenerationError("Image generation was cancelled.")

    if not isinstance(payload, dict):
        raise ImageGenerationError("Gemini returned an invalid image response.")
    try:
        parts = payload["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError):
        raise ImageGenerationError("Gemini returned no image candidate data.") from None

    image_blob = None
    media_type = "image/png"
    for part in parts:
        if not isinstance(part, dict):
            continue
        inline_data = part.get("inlineData") or part.get("inline_data")
        if isinstance(inline_data, dict):
            encoded = inline_data.get("data")
            if isinstance(encoded, str) and encoded:
                image_blob = encoded
                media_type = str(inline_data.get("mimeType") or inline_data.get("mime_type") or media_type)
                break
    if not image_blob:
        raise ImageGenerationError("Gemini did not return an image in the response.")
    try:
        content = base64.b64decode(image_blob, validate=True)
    except (ValueError, base64.binascii.Error):
        raise ImageGenerationError("Gemini returned invalid base64 image data.") from None
    if not content:
        raise ImageGenerationError("Gemini returned an empty image.")
    return GeneratedImage(content, media_type.lower(), None)
