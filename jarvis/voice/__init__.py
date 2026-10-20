"""Optional local push-to-talk speech recognition and text-to-speech."""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Slot

log = logging.getLogger(__name__)


class _CaptureWorker(QObject):
    recognized = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        stop_event: threading.Event,
        model_path: str,
        language: str,
    ) -> None:
        super().__init__()
        self._stop_event = stop_event
        self._model_path = model_path
        self._language = language.split("-", 1)[0]

    @Slot()
    def run(self) -> None:
        try:
            import numpy as np
            import sounddevice as sd
            from faster_whisper import WhisperModel

            audio_chunks = []
            stop_at = time.monotonic() + 120
            with sd.InputStream(samplerate=16000, channels=1, dtype="float32") as stream:
                while not self._stop_event.is_set() and time.monotonic() < stop_at:
                    audio, _ = stream.read(1600)
                    audio_chunks.append(audio[:, 0].copy())

            if not audio_chunks:
                self.failed.emit("No audio was captured.")
                return

            model = WhisperModel(
                self._model_path,
                device="cpu",
                compute_type="int8",
                local_files_only=True,
            )
            segments, _ = model.transcribe(
                np.concatenate(audio_chunks),
                language=self._language,
                vad_filter=True,
            )
            text = " ".join(segment.text.strip() for segment in segments).strip()
            if text:
                self.recognized.emit(text)
            else:
                self.failed.emit("No speech was recognized. Try again in a quieter place.")
        except Exception as exc:
            log.exception("Local speech recognition failed")
            self.failed.emit(str(exc))


class VoiceController(QObject):
    """Runs microphone capture and local transcription outside the GUI thread."""

    listening_changed = Signal(bool)
    transcription_ready = Signal(str)
    error = Signal(str)

    def __init__(self, settings, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._thread: QThread | None = None
        self._worker: _CaptureWorker | None = None
        self._stop_event: threading.Event | None = None

    @property
    def is_listening(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def start_listening(self) -> None:
        if self.is_listening:
            return

        model_path = str(self._settings.get("voice_model_path", "")).strip()
        if not model_path or not Path(model_path).is_dir():
            self.error.emit(
                "Voice needs a local faster-whisper model directory. "
                "Set voice_model_path in advanced_settings.ini."
            )
            return

        try:
            import sounddevice  # noqa: F401
            import faster_whisper  # noqa: F401
        except ImportError as exc:
            self.error.emit(
                "Local voice packages are not installed. Run: "
                "pip install sounddevice faster-whisper"
            )
            log.info("Voice unavailable: %s", exc)
            return

        self._stop_event = threading.Event()
        self._thread = QThread(self)
        self._worker = _CaptureWorker(
            self._stop_event,
            model_path,
            str(self._settings.get("voice_language", "en-US")),
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.recognized.connect(self.transcription_ready)
        self._worker.failed.connect(self.error)
        self._worker.recognized.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._worker.recognized.connect(self._worker.deleteLater)
        self._worker.failed.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._on_finished)
        self._thread.start()
        self.listening_changed.emit(True)

    def stop_listening(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()

    def stop(self) -> None:
        self.stop_listening()

    @Slot()
    def _on_finished(self) -> None:
        thread = self._thread
        self._thread = None
        self._worker = None
        self._stop_event = None
        if thread is not None:
            thread.deleteLater()
        self.listening_changed.emit(False)

    def speak(self, text: str) -> None:
        """Speak asynchronously when enabled; speech dependencies remain optional."""
        if not self._settings.get("tts_enabled", False) or not text.strip():
            return
        threading.Thread(
            target=self._speak_blocking,
            args=(text,),
            name="jarvis-tts",
            daemon=True,
        ).start()

    def _speak_blocking(self, text: str) -> None:
        try:
            import pyttsx3

            engine = pyttsx3.init()
            engine.setProperty("rate", int(self._settings.get("tts_rate", 175)))
            engine.setProperty("volume", float(self._settings.get("tts_volume", 0.9)))
            engine.say(text)
            engine.runAndWait()
        except Exception as exc:
            log.exception("Text-to-speech failed")
            self.error.emit(f"Text-to-speech failed: {exc}")
