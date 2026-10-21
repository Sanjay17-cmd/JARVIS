from threading import Event

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


class _CancellableRouter:
    def __init__(self):
        self.started = Event()
        self.calls = 0

    def has_builtin(self, text):
        return False

    def route_stream(self, text, on_chunk, cancel_event=None, on_reset=None):
        self.calls += 1
        if self.calls == 1:
            self.started.set()
            cancel_event.wait(2)
            return "stale response"
        on_chunk("fresh response")
        return "fresh response"


class _PredefinedRouter:
    last_response_is_predefined = True

    def has_builtin(self, text):
        return True

    def route(self, text):
        return "Welcome back!"


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


def test_cancelled_response_cannot_overwrite_a_later_response(
    qtbot, tmp_path, monkeypatch
):
    database.close()
    monkeypatch.setattr(database, "_db_path", lambda: tmp_path / "jarvis.db")
    router = _CancellableRouter()
    panel = InteractionPanel(
        StateManager(),
        EventBus(),
        router,
        settings=_Settings(),
    )
    qtbot.addWidget(panel)

    panel.set_input_text("first question")
    panel._on_send()
    qtbot.waitUntil(router.started.is_set, timeout=2000)
    panel._on_cancel()
    qtbot.waitUntil(lambda: panel._command_thread is None, timeout=5000)

    panel.set_input_text("second question")
    panel._on_send()
    qtbot.waitUntil(lambda: panel._command_thread is None, timeout=5000)
    history = database.load_conversation_history()

    assert any(item["content"] == "fresh response" for item in history)
    assert not any(item["content"] == "stale response" for item in history)
    panel.close()
    database.close()


def test_voice_chat_is_a_separate_window_and_can_switch_conversations(
    qtbot, tmp_path, monkeypatch
):
    from jarvis.ui.voice_chat_dialog import VoiceChatDialog

    database.close()
    monkeypatch.setattr(database, "_db_path", lambda: tmp_path / "jarvis.db")
    panel = InteractionPanel(
        StateManager(),
        EventBus(),
        _StreamingRouter(),
        settings=_Settings(),
    )
    qtbot.addWidget(panel)
    original_id = panel.current_conversation_id
    old_id = database.create_conversation("Older chat")
    database.save_conversation_message(
        "user", "An older voice conversation", 1.0, conversation_id=old_id
    )
    voice_chat = VoiceChatDialog(panel, _Settings())
    qtbot.addWidget(voice_chat)

    assert not panel.isVisible()
    voice_chat._new_chat()
    new_id = panel.current_conversation_id
    assert new_id != original_id
    assert voice_chat.conversations.currentData() == new_id
    voice_chat.conversations.setCurrentIndex(
        voice_chat.conversations.findData(old_id)
    )
    voice_chat._open_selected()
    assert panel.current_conversation_id == old_id
    assert "An older voice conversation" in voice_chat.history.toPlainText()

    voice_chat.close()
    panel.close()
    database.close()


def test_due_reminder_can_be_shown_as_a_chat_message(qtbot, tmp_path, monkeypatch):
    database.close()
    monkeypatch.setattr(database, "_db_path", lambda: tmp_path / "jarvis.db")
    panel = InteractionPanel(
        StateManager(),
        EventBus(),
        _StreamingRouter(),
        settings=_Settings(),
    )
    qtbot.addWidget(panel)
    emitted = []
    panel.message_added.connect(lambda role, text: emitted.append((role, text)))

    panel.add_reminder_message("Submit the report", "Due at 4 PM")

    history = database.load_conversation_history(
        conversation_id=panel.current_conversation_id
    )
    assert "Submit the report" in history[-1]["content"]
    assert emitted[-1][0] == "assistant"
    assert "Due at 4 PM" in emitted[-1][1]
    panel.close()
    database.close()


def test_predefined_response_has_a_small_source_marker(qtbot, tmp_path, monkeypatch):
    database.close()
    monkeypatch.setattr(database, "_db_path", lambda: tmp_path / "jarvis.db")
    panel = InteractionPanel(
        StateManager(),
        EventBus(),
        _PredefinedRouter(),
        settings=_Settings(),
    )
    qtbot.addWidget(panel)

    panel.set_input_text("hello")
    panel._on_send()

    assert panel._stream_bubble.text().startswith("◆ BUILT-IN RESPONSE\n")
    assert "Welcome back!" in panel._stream_bubble.text()
    panel.close()
    database.close()
