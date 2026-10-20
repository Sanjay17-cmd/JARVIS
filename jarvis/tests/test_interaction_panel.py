from jarvis.core.event_bus import EventBus
from jarvis.core.state import StateManager
from jarvis.scheduling import database
from jarvis.ui.interaction_panel import InteractionPanel


class _Settings:
    def get(self, key, default=None):
        return {
            "retain_conversation": True,
            "voice_model_path": "",
            "voice_language": "en-US",
            "tts_enabled": False,
        }.get(key, default)


class _StreamingRouter:
    def has_builtin(self, text):
        return False

    def route_stream(self, text, on_chunk):
        on_chunk("JARVIS ")
        on_chunk("reply")
        return "JARVIS reply"


def test_panel_streams_commands_and_persists_history(qtbot, tmp_path, monkeypatch):
    database.close()
    monkeypatch.setattr(database, "_db_path", lambda: tmp_path / "jarvis.db")
    panel = InteractionPanel(
        StateManager(),
        EventBus(),
        _StreamingRouter(),
        settings=_Settings(),
    )
    qtbot.addWidget(panel)
    panel.set_input_text("test question")
    panel._on_send()
    qtbot.waitUntil(lambda: panel._command_thread is None, timeout=5000)

    history = database.load_conversation_history()
    assert [(item["role"], item["content"]) for item in history] == [
        ("user", "test question"),
        ("assistant", "JARVIS reply"),
    ]
    assert panel._stream_bubble is not None
    assert panel._stream_bubble.text().startswith("JARVIS reply")
    panel.close()
    database.close()
