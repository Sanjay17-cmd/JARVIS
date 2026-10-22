from jarvis.ui.voice_setup_dialog import VoiceSetupDialog
from jarvis.voice import VoiceController
from jarvis.config.defaults import DEFAULTS


class Settings:
    def __init__(self):
        self.values = {
            "voice_enabled": True,
            "voice_model_id": "base.en",
            "voice_model_ready": False,
            "voice_microphone_id": -1,
            "tts_enabled": False,
            "tts_voice": "",
            "voice_auto_listen": DEFAULTS["voice_auto_listen"],
            "voice_silence_ms": DEFAULTS["voice_silence_ms"],
            "voice_interrupt_tts": DEFAULTS["voice_interrupt_tts"],
            "voice_language": "en-US",
        }

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value

    def save(self):
        pass


def test_voice_setup_lists_and_saves_an_alternate_speech_voice(
    qtbot, monkeypatch
):
    monkeypatch.setattr(
        VoiceController,
        "output_voices",
        staticmethod(lambda: [("voice-a", "Voice A"), ("voice-b", "Voice B")]),
    )
    settings = Settings()
    controller = VoiceController(settings)
    dialog = VoiceSetupDialog(settings, controller)
    qtbot.addWidget(dialog)

    index = dialog._tts_voice.findData("voice-b")
    assert index >= 0
    dialog._tts_voice.setCurrentIndex(index)
    dialog._tts_enabled.setChecked(True)

    assert settings.get("tts_voice") == "voice-b"
    assert settings.get("tts_enabled") is True
    dialog.close()


def test_voice_setup_persists_hands_free_silence_and_interrupt_options(
    qtbot, monkeypatch
):
    monkeypatch.setattr(VoiceController, "output_voices", staticmethod(lambda: []))
    settings = Settings()
    controller = VoiceController(settings)
    dialog = VoiceSetupDialog(settings, controller)
    qtbot.addWidget(dialog)

    dialog._auto_listen.setChecked(False)
    dialog._silence_ms.setValue(1400)
    dialog._interrupt_tts.setChecked(False)

    assert settings.get("voice_auto_listen") is False
    assert settings.get("voice_silence_ms") == 1400
    assert settings.get("voice_interrupt_tts") is False
    dialog.close()


def test_voice_setup_supports_south_indian_languages_with_multilingual_model(
    qtbot, monkeypatch
):
    monkeypatch.setattr(VoiceController, "output_voices", staticmethod(lambda: []))
    settings = Settings()
    controller = VoiceController(settings)
    dialog = VoiceSetupDialog(settings, controller)
    qtbot.addWidget(dialog)

    for language in ("ta", "te", "kn", "ml"):
        assert dialog._language.findData(language) >= 0

    dialog._language.setCurrentIndex(dialog._language.findData("ta"))

    assert settings.get("voice_language") == "ta"
    assert settings.get("voice_model_id") == "base"
    assert settings.get("voice_model_ready") is False
    assert dialog._model.currentText() == "base"
    dialog.close()


def test_capture_worker_stops_after_configured_silence_and_transcribes(
    monkeypatch,
):
    import sys
    import types
    import numpy as np
    from threading import Event
    from jarvis.voice import _CaptureWorker

    class FakeStream:
        def __init__(self, **_kwargs):
            self.samples = [
                np.zeros((1600, 1), dtype="float32"),
                np.full((1600, 1), 0.2, dtype="float32"),
                np.full((1600, 1), 0.2, dtype="float32"),
                np.zeros((1600, 1), dtype="float32"),
                np.zeros((1600, 1), dtype="float32"),
                np.zeros((1600, 1), dtype="float32"),
            ]
            self.read_count = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _frames):
            self.read_count += 1
            return self.samples.pop(0), False

    class FakeWhisperModel:
        def __init__(self, *_args, **_kwargs):
            pass

        def transcribe(self, audio, **_kwargs):
            assert len(audio) == 6 * 1600
            return [types.SimpleNamespace(text="hello jarvis")], None

    stream = FakeStream()
    monkeypatch.setitem(
        sys.modules,
        "sounddevice",
        types.SimpleNamespace(InputStream=lambda **kwargs: stream),
    )
    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        types.SimpleNamespace(WhisperModel=FakeWhisperModel),
    )
    worker = _CaptureWorker(Event(), "tiny.en", "en-US", -1, "cpu", "int8", 300)
    recognized = []
    started = []
    worker.recognized.connect(recognized.append)
    worker.speech_started.connect(lambda: started.append(True))

    worker.run()

    assert stream.read_count == 6
    assert recognized == ["hello jarvis"]
    assert started == [True]


def test_continuous_listening_restarts_after_an_empty_capture(monkeypatch):
    from jarvis.voice import QTimer

    settings = Settings()
    controller = VoiceController(settings)
    controller._listening_session = True
    scheduled = []
    restarted = []
    monkeypatch.setattr(
        QTimer, "singleShot", lambda delay, callback: scheduled.append((delay, callback))
    )
    controller.start_listening = lambda: restarted.append(True)

    controller._on_finished()

    assert len(scheduled) == 1
    assert scheduled[0][0] == 250
    scheduled[0][1]()
    assert restarted == [True]


def test_disabled_auto_listen_ends_session_after_capture():
    from jarvis.voice import VoiceController

    settings = Settings()
    settings.set("voice_auto_listen", False)
    controller = VoiceController(settings)
    controller._listening_session = True
    controller._segment_recognized = True

    controller._on_finished()

    assert controller.listening_session_active is False


def test_voice_activity_interrupts_speech_when_configured():
    settings = Settings()
    controller = VoiceController(settings)

    class SpeechEngine:
        stopped = False

        def stop(self):
            self.stopped = True

    engine = SpeechEngine()
    controller._tts_engine = engine

    controller._on_speech_started()

    assert engine.stopped is True


def test_interrupted_tts_stops_old_text_and_allows_new_reply(monkeypatch, qtbot):
    import sys
    import threading
    import time
    import types

    engines = []

    class SpeechEngine:
        def __init__(self):
            self.started = threading.Event()
            self.finished = threading.Event()
            self.stop_requested = threading.Event()
            self.text = ""

        def setProperty(self, *_args):
            pass

        def say(self, text):
            self.text = text

        def runAndWait(self):
            self.started.set()
            if self.text == "old answer":
                self.stop_requested.wait(3)
            self.finished.set()

        def stop(self):
            self.stop_requested.set()

    def make_engine():
        engine = SpeechEngine()
        engines.append(engine)
        return engine

    monkeypatch.setitem(
        sys.modules,
        "pyttsx3",
        types.SimpleNamespace(init=make_engine),
    )
    settings = Settings()
    settings.set("tts_enabled", True)
    controller = VoiceController(settings)
    finished_signals = []
    controller.speech_finished.connect(
        lambda: finished_signals.append(True)
    )

    controller.speak("old answer")
    deadline = time.monotonic() + 2
    while not engines and time.monotonic() < deadline:
        time.sleep(0.01)
    assert engines
    old_engine = engines[0]
    assert old_engine.started.wait(2)

    controller._on_speech_started()
    controller.speak("new answer")

    deadline = time.monotonic() + 3
    while len(engines) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert len(engines) == 2
    assert engines[1].finished.wait(2)
    assert old_engine.stop_requested.is_set()
    assert engines[1].text == "new answer"
    qtbot.waitUntil(lambda: len(finished_signals) == 1, timeout=2000)
