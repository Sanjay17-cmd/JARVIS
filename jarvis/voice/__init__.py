"""Optional local segmented speech recognition and text-to-speech."""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot

log = logging.getLogger(__name__)


class _CaptureWorker(QObject):
    recognized = Signal(str)
    failed = Signal(str)
    speech_started = Signal()

    def __init__(
        self,
        stop_event: threading.Event,
        model_path: str,
        language: str,
        device_index: int,
        device: str,
        compute_type: str,
        silence_ms: int,
    ) -> None:
        super().__init__()
        self._stop_event = stop_event
        self._model_path = model_path
        self._language = language.split("-", 1)[0]
        self._device_index = None if device_index < 0 else device_index
        self._device = device
        self._compute_type = compute_type
        self._silence_ms = silence_ms

    @Slot()
    def run(self) -> None:
        try:
            import numpy as np
            import sounddevice as sd
            from faster_whisper import WhisperModel

            audio_chunks = []
            speech_detected = False
            silent_ms = 0
            stop_at = time.monotonic() + 120
            with sd.InputStream(
                samplerate=16000,
                channels=1,
                dtype="float32",
                device=self._device_index,
            ) as stream:
                while not self._stop_event.is_set() and time.monotonic() < stop_at:
                    audio, _ = stream.read(1600)
                    samples = audio[:, 0].copy()
                    audio_chunks.append(samples)
                    rms = float(np.sqrt(np.mean(np.square(samples))))
                    if rms >= 0.012:
                        silent_ms = 0
                        if not speech_detected:
                            speech_detected = True
                            self.speech_started.emit()
                    elif speech_detected:
                        silent_ms += 100
                        if silent_ms >= self._silence_ms:
                            break

            if not audio_chunks:
                self.failed.emit("No audio was captured.")
                return
            if not speech_detected:
                if self._stop_event.is_set():
                    self.failed.emit("No speech was detected.")
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
    speech_finished = Signal()

    def __init__(self, settings, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._tts_lock = threading.Lock()
        self._tts_state_lock = threading.Lock()
        self._tts_engine = None
        self._tts_generation = 0
        self._thread: QThread | None = None
        self._worker: _CaptureWorker | None = None
        self._setup_thread: QThread | None = None
        self._setup_worker: _ModelSetupWorker | None = None
        self._stop_event: threading.Event | None = None
        self._listening_session = False
        self._segment_recognized = False
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

        self._listening_session = True
        self._segment_recognized = False
        self._stop_event = threading.Event()
        self._thread = QThread(self)
        self._worker = _CaptureWorker(
            self._stop_event,
            model_path,
            str(self._settings.get("voice_language", "en-US")),
            int(self._settings.get("voice_microphone_id", -1)),
            str(self._settings.get("voice_device", "cpu")),
            str(self._settings.get("voice_compute_type", "int8")),
            max(300, min(
                int(self._settings.get("voice_silence_ms", 900)), 5000
            )),
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.recognized.connect(self._on_transcription)
        self._worker.failed.connect(self.error)
        self._worker.speech_started.connect(self._on_speech_started)
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
        self._listening_session = False
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
        auto_listen = bool(self._settings.get("voice_auto_listen", True))
        should_retry = (
            self._listening_session and auto_listen and not self._segment_recognized
        )
        if self._listening_session and not auto_listen:
            self._listening_session = False
        self.listening_changed.emit(False)
        if should_retry:
            QTimer.singleShot(250, self.start_listening)

    @Slot(str)
    def _on_transcription(self, text: str) -> None:
        self._segment_recognized = True
        self.transcription_ready.emit(text)

    def speak(self, text: str) -> None:
        """Speak asynchronously when enabled; speech dependencies remain optional."""
        if not self._settings.get("tts_enabled", False) or not text.strip():
            return
        with self._tts_state_lock:
            self._tts_generation += 1
            generation = self._tts_generation
        threading.Thread(
            target=self._speak_blocking,
            args=(text, generation),
            name="jarvis-tts",
            daemon=True,
        ).start()

    @Slot()
    def _on_speech_started(self) -> None:
        if self._settings.get("voice_interrupt_tts", True):
            self.stop_speaking()

    def stop_speaking(self) -> None:
        with self._tts_state_lock:
            self._tts_generation += 1
            engine = self._tts_engine
        if engine is not None:
            try:
                engine.stop()
            except Exception as exc:
                log.warning("Could not interrupt speech output: %s", exc)

    @property
    def listening_session_active(self) -> bool:
        return self._listening_session

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

    def _speak_blocking(self, text: str, generation: int | None = None) -> None:
        with self._tts_lock:
            engine = None
            try:
                import pyttsx3

                with self._tts_state_lock:
                    if generation is not None and generation != self._tts_generation:
                        return
                engine = pyttsx3.init()
                with self._tts_state_lock:
                    if generation is not None and generation != self._tts_generation:
                        engine.stop()
                        return
                    self._tts_engine = engine
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
            finally:
                with self._tts_state_lock:
                    current_generation = self._tts_generation
                    if self._tts_engine is engine:
                        self._tts_engine = None
                if engine is not None:
                    try:
                        engine.stop()
                    except Exception:
                        log.debug("Speech engine already stopped", exc_info=True)
                if generation is None or generation == current_generation:
                    self.speech_finished.emit()
