"""
assets/__init__.py — Asset path helpers and animation cache.
"""
from __future__ import annotations
import os
from pathlib import Path

# Assets bundled with the package live next to this file
_PKG_DIR = Path(__file__).parent
IMAGES_DIR = _PKG_DIR / "images"
ICONS_DIR  = _PKG_DIR / "icons"
SOUNDS_DIR = _PKG_DIR / "sounds"

# Pre-rendered animation frames cache (populated on first use)
_FRAME_CACHE: dict[str, list] = {}


def get_frames(state: str, size: int = 120) -> list:
    """Return cached animation frames for *state*, generating them if needed."""
    global _FRAME_CACHE
    cache_key = f"{state}_{size}"
    if cache_key not in _FRAME_CACHE:
        from .robot_painter import ensure_assets
        frames = ensure_assets(IMAGES_DIR, size=size)
        for s, imgs in frames.items():
            _FRAME_CACHE[f"{s}_{size}"] = imgs
    return _FRAME_CACHE.get(cache_key, [])
