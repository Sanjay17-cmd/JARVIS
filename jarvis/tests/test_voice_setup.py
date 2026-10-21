from jarvis.ui.voice_setup_dialog import VoiceSetupDialog
from jarvis.voice import VoiceController


class Settings:
    def __init__(self):
        self.values = {
            "voice_enabled": True,
            "voice_model_id": "base.en",
            "voice_model_ready": False,
            "voice_microphone_id": -1,
            "tts_enabled": False,
            "tts_voice": "",
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
