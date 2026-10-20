"""
plugins/__init__.py — Plugin discovery and registry stub.
Plugins are discoverable Python packages in the plugins/ directory.
"""
from __future__ import annotations
import logging
log = logging.getLogger(__name__)


class PluginRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, object] = {}

    def discover(self, plugin_dir: str = "plugins") -> None:
        log.debug("Plugin discovery not yet implemented (Phase 5).")

    def enable(self, name: str) -> None:
        log.warning("Plugin system stub — '%s' not loaded.", name)

    def list_plugins(self) -> list[str]:
        return list(self._plugins.keys())
