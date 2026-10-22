"""OpenRouter image generation using its dedicated Images API."""
from __future__ import annotations

import base64
import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from threading import Event

from jarvis.ai.free_models import (
    FreeModelCatalogError,
    list_free_openrouter_models,
)


class ImageGenerationError(RuntimeError):
    pass


@dataclass(frozen=True)
class GeneratedImage:
    content: bytes
    media_type: str
    cost_usd: float | None = None


def list_free_image_models(*, timeout: int = 15) -> list[dict[str, str]]:
    """Return only catalog image models explicitly free across all listed pricing."""
    try:
        return list_free_openrouter_models("image", timeout=timeout)
    except FreeModelCatalogError as exc:
        raise ImageGenerationError(str(exc)) from exc


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
            "No OpenRouter API key is configured. Add one in AI Pipeline Settings."
        )
    if not model:
        raise ImageGenerationError("Enter an OpenRouter image model ID.")
    if cancel_event is not None and cancel_event.is_set():
        raise ImageGenerationError("Image generation was cancelled.")
    free_models = list_free_image_models(timeout=min(timeout, 30))
    if not any(item["id"] == model for item in free_models):
        raise ImageGenerationError(
            f"'{model}' is not currently listed by OpenRouter as a zero-priced "
            "image model. No image request was sent."
        )
    if cancel_event is not None and cancel_event.is_set():
        raise ImageGenerationError("Image generation was cancelled.")

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
