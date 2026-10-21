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
        device_index: int,
        device: str,
        compute_type: str,
    ) -> None:
        super().__init__()
        self._stop_event = stop_event
        self._model_path = model_path
        self._language = language.split("-", 1)[0]
        self._device_index = None if device_index < 0 else device_index
        self._device = device
        self._compute_type = compute_type

    @Slot()
    def run(self) -> None:
        try:
            import numpy as np
            import sounddevice as sd
            from faster_whisper import WhisperModel

            audio_chunks = []
            stop_at = time.monotonic() + 120
            with sd.InputStream(
                samplerate=16000,
                channels=1,
                dtype="float32",
                device=self._device_index,
            ) as stream:
                while not self._stop_event.is_set() and time.monotonic() < stop_at:
                    audio, _ = stream.read(1600)
                    audio_chunks.append(audio[:, 0].copy())

            if not audio_chunks:
                self.failed.emit("No audio was captured.")
                return

            model = WhisperModel(
                self._model_path,
                device=self._device,
                compute_type=self._compute_type,
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


class _ModelSetupWorker(QObject):
    progress = Signal(str)
    initialized = Signal()
    failed = Signal(str)

    def __init__(self, model: str, device: str, compute_type: str) -> None:
        super().__init__()
        self._model = model
        self._device = device
        self._compute_type = compute_type

    @Slot()
    def run(self) -> None:
        try:
            from faster_whisper import WhisperModel

            self.progress.emit(f"Initializing {self._model}; first setup may download it.")
            WhisperModel(
                self._model,
                device=self._device,
                compute_type=self._compute_type,
            )
            self.initialized.emit()
        except Exception as exc:
            log.exception("Voice model initialization failed")
            self.failed.emit(
                f"Model initialization failed: {exc}. Check internet access for "
                "the first download, available disk space, and the model path."
            )


class VoiceController(QObject):
    """Runs microphone capture and local transcription outside the GUI thread."""

    listening_changed = Signal(bool)
    transcription_ready = Signal(str)
    error = Signal(str)
    setup_progress = Signal(str)
    model_initialized = Signal(str)
    setup_failed = Signal(str)

    def __init__(self, settings, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._tts_lock = threading.Lock()
        self._thread: QThread | None = None
        self._worker: _CaptureWorker | None = None
        self._setup_thread: QThread | None = None
        self._setup_worker: _ModelSetupWorker | None = None
        self._stop_event: threading.Event | None = None
        self._model_ready = bool(settings.get("voice_model_ready", False))

    @property
    def is_listening(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def start_listening(self) -> None:
        if self.is_listening:
            return
        if not self._settings.get("voice_enabled", False):
            self.error.emit("Voice is disabled in Settings. Enable it in Voice Setup.")
            return

        model_path = str(
            self._settings.get("voice_model_path", "")
            or self._settings.get("voice_model_id", "base.en")
        ).strip()
        if not self._model_ready:
            self.error.emit(
                f"Voice model '{model_path}' is not initialized. Open Settings → "
                "Voice Setup and select Initialize Model (first-time download needs consent)."
            )
            return

        try:
            import sounddevice  # noqa: F401
            import faster_whisper  # noqa: F401
        except ImportError as exc:
            self.error.emit(
                "Voice dependencies are missing. Install with: "
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
            int(self._settings.get("voice_microphone_id", -1)),
            str(self._settings.get("voice_device", "cpu")),
            str(self._settings.get("voice_compute_type", "int8")),
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

    def initialize_model(self) -> None:
        if self._setup_thread is not None or self.is_listening:
            self.setup_failed.emit("Voice setup or recording is already in progress.")
            return
        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            self.setup_failed.emit(
                "Install faster-whisper first: pip install faster-whisper"
            )
            return
        model = str(
            self._settings.get("voice_model_path", "")
            or self._settings.get("voice_model_id", "base.en")
        ).strip()
        if not model:
            self.setup_failed.emit("Choose a model name or browse to a local model folder.")
            return
        path = Path(model)
        if ("/" in model or "\\" in model) and not path.is_dir():
            self.setup_failed.emit(f"Model directory does not exist: {path}")
            return
        self._settings.set("voice_model_ready", False)
        self._setup_thread = QThread(self)
        self._setup_worker = _ModelSetupWorker(
            model,
            str(self._settings.get("voice_device", "cpu")),
            str(self._settings.get("voice_compute_type", "int8")),
        )
        self._setup_worker.moveToThread(self._setup_thread)
        self._setup_thread.started.connect(self._setup_worker.run)
        self._setup_worker.progress.connect(self.setup_progress)
        self._setup_worker.initialized.connect(self._on_model_initialized)
        self._setup_worker.failed.connect(self.setup_failed)
        self._setup_worker.initialized.connect(self._setup_thread.quit)
        self._setup_worker.failed.connect(self._setup_thread.quit)
        self._setup_worker.initialized.connect(self._setup_worker.deleteLater)
        self._setup_worker.failed.connect(self._setup_worker.deleteLater)
        self._setup_thread.finished.connect(self._on_setup_finished)
        self._setup_thread.start()

    @Slot()
    def _on_model_initialized(self) -> None:
        model = str(
            self._settings.get("voice_model_path", "")
            or self._settings.get("voice_model_id", "base.en")
        ).strip()
        self._settings.set("voice_model_ready", True)
        self._settings.save()
        self._model_ready = True
        self.model_initialized.emit(model)

    @Slot()
    def _on_setup_finished(self) -> None:
        thread = self._setup_thread
        self._setup_thread = None
        self._setup_worker = None
        if thread is not None:
            thread.deleteLater()

    @staticmethod
    def input_devices() -> list[tuple[int, str]]:
        import sounddevice as sd

        return [
            (index, device["name"])
            for index, device in enumerate(sd.query_devices())
            if int(device.get("max_input_channels", 0)) > 0
        ]

    def test_microphone(self) -> str:
        try:
            devices = self.input_devices()
            selected = int(self._settings.get("voice_microphone_id", -1))
            if selected < 0:
                selected = int(__import__("sounddevice").default.device[0])
            if selected < 0 or selected >= len(__import__("sounddevice").query_devices()):
                raise RuntimeError("No usable microphone is selected.")
            import sounddevice as sd

            sd.rec(
                int(0.5 * 16000),
                samplerate=16000,
                channels=1,
                dtype="float32",
                device=selected,
                blocking=True,
            )
            return f"Microphone test recorded successfully (device {selected})."
        except Exception as exc:
            log.exception("Microphone test failed")
            return f"Microphone unavailable: {exc}"

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

    def test_speech(self) -> None:
        threading.Thread(
            target=self._speak_blocking,
            args=("JARVIS text to speech test.",),
            name="jarvis-tts-test",
            daemon=True,
        ).start()

    @staticmethod
    def output_voices() -> list[tuple[str, str]]:
        """Return installed system speech voices as (voice ID, display name)."""
        import pyttsx3

        engine = pyttsx3.init()
        try:
            return [
                (str(voice.id), str(voice.name))
                for voice in engine.getProperty("voices")
            ]
        finally:
            engine.stop()

    def _speak_blocking(self, text: str) -> None:
        with self._tts_lock:
            try:
                import pyttsx3

                engine = pyttsx3.init()
                engine.setProperty("rate", int(self._settings.get("tts_rate", 175)))
                engine.setProperty("volume", float(self._settings.get("tts_volume", 0.9)))
                voice_id = str(self._settings.get("tts_voice", ""))
                if voice_id:
                    engine.setProperty("voice", voice_id)
                engine.say(text)
                engine.runAndWait()
            except Exception as exc:
                log.exception("Text-to-speech failed")
                self.error.emit(f"Text-to-speech failed: {exc}")
