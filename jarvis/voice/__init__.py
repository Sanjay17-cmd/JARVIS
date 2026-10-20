"""
voice/__init__.py — Voice module stub.
Wake-word detection and speech recognition planned for Phase 2.
"""
from __future__ import annotations
import logging
log = logging.getLogger(__name__)


class MicrophoneInterface:
    """Stub — will integrate sherpa-onnx in Phase 2."""
    def start_listening(self) -> bool:
        log.warning("Voice not yet implemented (Phase 2).")
        return False

    def stop_listening(self) -> None:
        pass
