"""Strict OpenRouter catalogue checks for zero-priced model routes."""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request


class FreeModelCatalogError(RuntimeError):
    pass


def is_verified_free_model(model: dict, modality: str) -> bool:
    model_id = model.get("id")
    architecture = model.get("architecture")
    modalities = (
        architecture.get("output_modalities", [])
        if isinstance(architecture, dict) else []
    )
    pricing = model.get("pricing")
    if (
        not isinstance(model_id, str)
        or not model_id.endswith(":free")
        or not isinstance(modalities, list)
        or modality not in modalities
        or not isinstance(pricing, dict)
        or not pricing
    ):
        return False
    try:
        return all(float(value) == 0 for value in pricing.values())
    except (TypeError, ValueError):
        return False


def list_free_openrouter_models(
    modality: str, *, timeout: int = 15
) -> list[dict[str, str]]:
    if modality not in {"text", "image"}:
        raise ValueError("Only text and image model catalogs are supported.")
    request = urllib.request.Request(
        f"https://openrouter.ai/api/v1/models?output_modalities={modality}",
        headers={"Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise FreeModelCatalogError(
            f"Could not check OpenRouter's free {modality} models "
            f"(HTTP {exc.code})."
        ) from None
    except urllib.error.URLError as exc:
        reason = exc.reason
        message = (
            "OpenRouter model check timed out."
            if isinstance(reason, (TimeoutError, socket.timeout))
            else "Could not connect to OpenRouter to check free models."
        )
        raise FreeModelCatalogError(message) from None
    except (TimeoutError, socket.timeout):
        raise FreeModelCatalogError("OpenRouter model check timed out.") from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise FreeModelCatalogError(
            "OpenRouter returned an invalid model catalogue response."
        ) from None
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise FreeModelCatalogError(
            "OpenRouter returned an invalid model catalogue response."
        )
    models = []
    for item in payload["data"]:
        if isinstance(item, dict) and is_verified_free_model(item, modality):
            models.append({
                "id": str(item["id"]),
                "name": str(item.get("name") or item["id"]),
                "free": True,
            })
    return sorted(models, key=lambda item: item["name"].casefold())
