"""Consent-based setup and diagnostics for local voice features."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel,
    QMessageBox, QProgressBar, QPushButton, QSpinBox, QVBoxLayout,
)

from jarvis.voice import VoiceController

_MODELS = ("tiny.en", "base.en", "small.en", "tiny", "base", "small")

_LANGUAGES = (
    ("English", "en-US"),
    ("Tamil", "ta"),
    ("Telugu", "te"),
    ("Kannada", "kn"),
    ("Malayalam", "ml"),
)


class VoiceSetupDialog(QDialog):
    def __init__(self, settings, controller: VoiceController, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._voice = controller
        self.setWindowTitle("Voice Setup")
        self.setMinimumWidth(520)
        self.setStyleSheet(
            "QDialog,QWidget{background:rgba(8,18,42,235);color:#c0e8ff;"
            "font-family:'Segoe UI',Arial;font-size:12px;}"
            "QComboBox{background:rgba(0,30,60,220);padding:5px;}"
            "QPushButton{background:rgba(0,150,200,160);color:white;"
            "border:1px solid rgba(0,200,255,100);border-radius:6px;padding:6px;}"
        )
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Voice uses local speech recognition. Choose a model and explicitly "
            "initialize it; the first initialization may download model files."
        ))
        self._enabled = QCheckBox("Enable microphone voice input")
        self._enabled.setChecked(bool(settings.get("voice_enabled", False)))
        self._enabled.toggled.connect(self._save_settings)
        layout.addWidget(self._enabled)
        self._auto_listen = QCheckBox(
            "Keep listening after each reply (hands-free conversation)"
        )
        self._auto_listen.setChecked(
            bool(settings.get("voice_auto_listen", True))
        )
        self._auto_listen.toggled.connect(self._save_voice_behavior)
        layout.addWidget(self._auto_listen)
        silence_row = QHBoxLayout()
        silence_row.addWidget(QLabel("Stop after silence:"))
        self._silence_ms = QSpinBox()
        self._silence_ms.setRange(300, 5000)
        self._silence_ms.setSingleStep(100)
        self._silence_ms.setSuffix(" ms")
        self._silence_ms.setValue(int(settings.get("voice_silence_ms", 900)))
        self._silence_ms.valueChanged.connect(self._save_voice_behavior)
        silence_row.addWidget(self._silence_ms)
        silence_row.addStretch()
        layout.addLayout(silence_row)
        self._interrupt_tts = QCheckBox(
            "Interrupt JARVIS speech when I start talking"
        )
        self._interrupt_tts.setChecked(
            bool(settings.get("voice_interrupt_tts", True))
        )
        self._interrupt_tts.toggled.connect(self._save_voice_behavior)
        layout.addWidget(self._interrupt_tts)

        layout.addWidget(QLabel("Speech recognition language:"))
        self._language = QComboBox()
        for label, language in _LANGUAGES:
            self._language.addItem(label, language)
        language_index = self._language.findData(
            str(settings.get("voice_language", "en-US"))
        )
        if language_index >= 0:
            self._language.setCurrentIndex(language_index)
        self._language.currentIndexChanged.connect(self._save_language)
        layout.addWidget(self._language)
        layout.addWidget(QLabel(
            "Tamil, Telugu, Kannada, and Malayalam use multilingual Whisper "
            "models (tiny, base, or small), not English-only .en models. "
            "Spoken replies depend on matching Windows voices being installed."
        ))

        self._tts_enabled = QCheckBox("Speak every assistant response")
        self._tts_enabled.setChecked(bool(settings.get("tts_enabled", False)))
        self._tts_enabled.toggled.connect(self._save_tts_settings)
        layout.addWidget(self._tts_enabled)
        layout.addWidget(QLabel("Speech voice:"))
        self._tts_voice = QComboBox()
        self._tts_voice.addItem("System default", "")
        try:
            for voice_id, name in self._voice.output_voices():
                self._tts_voice.addItem(name, voice_id)
        except Exception as exc:
            self._tts_voice.setToolTip(f"Could not enumerate system voices: {exc}")
        current_voice = str(settings.get("tts_voice", ""))
        voice_index = self._tts_voice.findData(current_voice)
        if voice_index >= 0:
            self._tts_voice.setCurrentIndex(voice_index)
        self._tts_voice.currentIndexChanged.connect(self._save_tts_settings)
        layout.addWidget(self._tts_voice)

        layout.addWidget(QLabel("Recognition model (base.en is the CPU-friendly default):"))
        self._model = QComboBox()
        self._model.setEditable(True)
        self._model.addItems(_MODELS)
        current_model = settings.get("voice_model_id", "base.en")
        if settings.get("voice_model_path"):
            current_model = settings.get("voice_model_path")
        self._model.setCurrentText(str(current_model))
        self._model.currentTextChanged.connect(self._save_model)
        layout.addWidget(self._model)
        browse_row = QHBoxLayout()
        self._path_label = QLabel()
        self._path_label.setWordWrap(True)
        browse = QPushButton("Browse local model…")
        browse.clicked.connect(self._browse_model)
        browse_row.addWidget(browse)
        browse_row.addWidget(self._path_label, 1)
        layout.addLayout(browse_row)

        layout.addWidget(QLabel("Microphone:"))
        self._microphone = QComboBox()
        self._microphone.addItem("System default", -1)
        try:
            for index, name in self._voice.input_devices():
                self._microphone.addItem(f"{name} (device {index})", index)
        except Exception as exc:
            self._microphone.setToolTip(str(exc))
        selected = int(settings.get("voice_microphone_id", -1))
        index = self._microphone.findData(selected)
        if index >= 0:
            self._microphone.setCurrentIndex(index)
        self._microphone.currentIndexChanged.connect(self._save_settings)
        layout.addWidget(self._microphone)

        buttons = QHBoxLayout()
        self._initialize = QPushButton("Initialize / Download Model")
        self._initialize.clicked.connect(self._initialize_model)
        self._test_mic = QPushButton("Test Microphone")
        self._test_mic.clicked.connect(self._test_microphone)
        self._test_transcription = QPushButton("Test Transcription")
        self._test_transcription.clicked.connect(self._test_transcription_run)
        self._stop_transcription = QPushButton("Stop Recording")
        self._stop_transcription.clicked.connect(self._voice.stop_listening)
        self._test_tts = QPushButton("Test Text-to-Speech")
        self._test_tts.clicked.connect(self._test_speech)
        buttons.addWidget(self._initialize)
        buttons.addWidget(self._test_mic)
        buttons.addWidget(self._test_transcription)
        buttons.addWidget(self._stop_transcription)
        buttons.addWidget(self._test_tts)
        layout.addLayout(buttons)
        self._progress = QProgressBar()
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._progress.hide()
        layout.addWidget(self._progress)
        self._status = QLabel()
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        layout.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)

        self._voice.setup_progress.connect(self._on_progress)
        self._voice.model_initialized.connect(self._on_initialized)
        self._voice.setup_failed.connect(self._on_setup_error)
        self._voice.error.connect(self._on_setup_error)
        self._voice.transcription_ready.connect(
            lambda text: self._set_status(f"Transcription test: {text}")
        )
        self._voice.listening_changed.connect(self._on_listening)
        self._update_model_label()
        self._set_status(self._diagnostic())
        from jarvis.ui.dialog_window import configure_dialog_window
        configure_dialog_window(self, self._settings)

    def _save_settings(self, *_args) -> None:
        self._settings.set("voice_enabled", self._enabled.isChecked())
        self._settings.set("voice_microphone_id", int(self._microphone.currentData()))
        self._settings.save()

    def _save_voice_behavior(self, *_args) -> None:
        self._settings.set("voice_auto_listen", self._auto_listen.isChecked())
        self._settings.set("voice_silence_ms", self._silence_ms.value())
        self._settings.set("voice_interrupt_tts", self._interrupt_tts.isChecked())
        self._settings.save()

    def _save_language(self, *_args) -> None:
        language = str(self._language.currentData() or "en-US")
        self._settings.set("voice_language", language)
        model_path = str(self._settings.get("voice_model_path", "")).strip()
        model = model_path or str(
            self._settings.get("voice_model_id", "base.en")
        ).strip()
        if not model_path and language != "en-US" and model.endswith(".en"):
            model = model[:-3]
            self._settings.set("voice_model_id", model)
            self._settings.set("voice_model_path", "")
            self._settings.set("voice_model_ready", False)
            self._model.setCurrentText(model)
            self._update_model_label()
        self._settings.save()

    def _save_tts_settings(self, *_args) -> None:
        self._settings.set("tts_enabled", self._tts_enabled.isChecked())
        self._settings.set("tts_voice", str(self._tts_voice.currentData() or ""))
        self._settings.save()

    def _save_model(self, value: str) -> None:
        value = value.strip()
        if not value:
            return
        if Path(value).is_dir():
            self._settings.set("voice_model_path", value)
        else:
            self._settings.set("voice_model_path", "")
            self._settings.set("voice_model_id", value)
        self._settings.set("voice_model_ready", False)
        self._settings.save()
        self._update_model_label()

    def _browse_model(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select local model directory")
        if path:
            self._model.setCurrentText(path)
            self._save_model(path)

    def _update_model_label(self) -> None:
        model = self._settings.get("voice_model_path") or self._settings.get("voice_model_id", "base.en")
        ready = bool(self._settings.get("voice_model_ready", False))
        self._path_label.setText(f"Selected: {model}")
        if ready:
            self._status.setText(f"Model ready: {model}")

    def _diagnostic(self) -> str:
        try:
            import sounddevice  # noqa: F401
        except ImportError:
            return "Microphone dependency missing: pip install sounddevice"
        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            return "Recognition dependency missing: pip install faster-whisper"
        if not self._settings.get("voice_model_ready", False):
            return "Model not initialized. Click Initialize / Download Model to start setup."
        return "Voice setup is ready."

    def _initialize_model(self) -> None:
        self._save_model(self._model.currentText())
        self._save_settings()
        self._initialize.setEnabled(False)
        self._progress.setRange(0, 0)
        self._progress.show()
        self._set_status("Initializing model in the background. The UI remains responsive…")
        self._voice.initialize_model()

    def _test_microphone(self) -> None:
        self._save_settings()
        self._set_status(self._voice.test_microphone())

    def _test_transcription_run(self) -> None:
        self._save_settings()
        self._set_status("Listening for one test utterance. Click Stop Recording when done.")
        self._voice.start_listening()

    def _test_speech(self) -> None:
        try:
            import pyttsx3  # noqa: F401
        except ImportError:
            self._set_status("TTS dependency missing: pip install pyttsx3")
            return
        self._voice.test_speech()
        self._set_status("TTS test started. If you hear no speech, check Windows output volume.")

    def _on_progress(self, message: str) -> None:
        self._set_status(message)

    def _on_initialized(self, model: str) -> None:
        self._progress.hide()
        self._progress.setRange(0, 1)
        self._initialize.setEnabled(True)
        self._update_model_label()
        self._set_status(f"Model initialized and ready: {model}")

    def _on_setup_error(self, message: str) -> None:
        self._progress.hide()
        self._progress.setRange(0, 1)
        self._initialize.setEnabled(True)
        self._set_status(message)

    def _on_listening(self, active: bool) -> None:
        if not active:
            return
        self._set_status("Recording. Click the microphone button in chat to stop and transcribe.")

    def _set_status(self, text: str) -> None:
        self._status.setText(text)
        self._status.setStyleSheet(
            "color:#ff8888" if any(
                token in text.casefold() for token in ("failed", "missing", "unavailable", "error")
            ) else "color:#c0e8ff"
        )
