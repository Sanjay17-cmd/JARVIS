"""
vision/__init__.py — Vision module stub.
Camera capture and OpenCV/MediaPipe integration planned for Phase 3.
"""
from __future__ import annotations

import logging
log = logging.getLogger(__name__)


class CameraInterface:
    """
    Stub for future OpenCV webcam capture.
    Placeholder that will be replaced in Phase 3.
    """
    def __init__(self) -> None:
        self._active = False
        log.debug("CameraInterface stub initialised (no camera opened).")

    def start(self) -> bool:
        log.warning("Camera not yet implemented (Phase 3).")
        return False

    def stop(self) -> None:
        self._active = False

    @property
    def is_active(self) -> bool:
        return self._active
