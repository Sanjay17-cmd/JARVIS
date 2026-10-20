"""
memory/__init__.py — SQLite-backed memory service stub.
Full persistent memory planned for Phase 2/3.
"""
from __future__ import annotations
import logging
log = logging.getLogger(__name__)


class MemoryService:
    """Stub — will use SQLite for command history and user memory."""
    def store(self, key: str, value: str) -> None:
        log.debug("Memory.store('%s') — not yet persisted.", key)

    def recall(self, key: str) -> str | None:
        return None

    def all_keys(self) -> list[str]:
        return []
