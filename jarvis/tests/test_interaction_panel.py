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


class _Gateway:
    def __init__(self):
        self.last_provider = "openrouter"
        self.last_model = "test/model"


class _ModelStreamingRouter(_StreamingRouter):
    def __init__(self, gateway):
        self.gateway = gateway

    def route_stream(self, text, on_chunk):
        self.gateway.last_provider = "openrouter"
        self.gateway.last_model = "test/model"
        return super().route_stream(text, on_chunk)


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
    assert panel._stream_bubble._model_caption.text() == "Local response"
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

    assert panel._stream_bubble.text().startswith("◆ ")
    assert "Welcome back!" in panel._stream_bubble.text()
    assert panel._stream_bubble._model_caption.text() == "Built-in response"
    panel.close()


def test_ai_response_shows_actual_model_below_response(qtbot, tmp_path, monkeypatch):
    database.close()
    monkeypatch.setattr(database, "_db_path", lambda: tmp_path / "jarvis.db")
    gateway = _Gateway()
    panel = InteractionPanel(
        StateManager(),
        EventBus(),
        _ModelStreamingRouter(gateway),
        settings=_Settings(),
        ai_gateway=gateway,
    )
    qtbot.addWidget(panel)
    panel.set_input_text("test question")
    panel._on_send()
    qtbot.waitUntil(lambda: panel._command_thread is None, timeout=5000)

    assert panel._stream_bubble._model_caption.text() == "openrouter · test/model"
    history = database.load_conversation_history()
    assert history[-1]["model_label"] == "openrouter · test/model"
    panel.close()
    database.close()
    database.close()


def test_search_citations_render_as_clickable_source_links(qtbot):
    from jarvis.ui.interaction_panel import _MessageBubble

    bubble = _MessageBubble("Answer")
    qtbot.addWidget(bubble)
    bubble.set_response_text(
        "Answer\n\nSources (via brave):\n"
        "- [Python downloads](https://www.python.org/downloads/)"
    )

    assert bubble.openExternalLinks()
    assert 'href="https://www.python.org/downloads/"' in bubble.text()
    bubble.close()


def test_web_search_answer_has_distinct_marker_from_predefined_response():
    from jarvis.ui.interaction_panel import _MessageBubble

    answer = (
        "Answer\n\nSources (via openrouter):\n"
        "- [OpenRouter](https://openrouter.ai/)"
    )
    bubble = _MessageBubble(answer, web_search=True)

    assert bubble.text().startswith("🌐 Answer")
    assert bubble.toolTip().startswith("Web-search answer")
    assert "◆" not in bubble.text()
    bubble.close()


def test_search_marker_requires_provider_sources_and_link():
    assert InteractionPanel._has_search_sources(
        "Answer\n\nSources (via brave):\n- [Source](https://example.com)"
    )
    assert not InteractionPanel._has_search_sources("AI answer without a search")
    assert not InteractionPanel._has_search_sources(
        "Sources (via brave):\n- A source title without a link"
    )


def test_confirmation_controls_offer_yes_and_no_without_blocking_chat(qtbot):
    from PySide6.QtWidgets import QPushButton

    panel = InteractionPanel(
        StateManager(), EventBus(), _StreamingRouter(), settings=_Settings()
    )
    qtbot.addWidget(panel)
    answers = []
    panel._queue_confirmation_reply = answers.append
    panel._show_confirmation_controls()
    buttons = panel._confirmation_row.findChildren(QPushButton)

    assert [button.text() for button in buttons] == ["Yes", "No"]
    buttons[0].click()
    assert answers == ["yes"]
    assert not buttons[0].isEnabled()
    panel.close()


def test_tts_completion_reopens_continuous_microphone(qtbot, monkeypatch):
    panel = InteractionPanel(
        StateManager(), EventBus(), _StreamingRouter(), settings=_Settings()
    )
    qtbot.addWidget(panel)
    scheduled = []
    monkeypatch.setattr(
        panel, "_schedule_voice_restart", lambda: scheduled.append(True)
    )

    panel._on_speech_finished()

    assert scheduled == [True]
    panel.close()


def test_voice_restart_waits_until_capture_thread_finishes(qtbot, monkeypatch):
    from jarvis.ui.interaction_panel import QTimer

    panel = InteractionPanel(
        StateManager(), EventBus(), _StreamingRouter(), settings=_Settings()
    )
    qtbot.addWidget(panel)

    class Voice:
        listening_session_active = True
        is_listening = True
        starts = 0

        def start_listening(self):
            self.starts += 1

    voice = Voice()
    panel._voice = voice
    scheduled = []
    monkeypatch.setattr(
        QTimer, "singleShot", lambda delay, callback: scheduled.append((delay, callback))
    )

    panel._restart_voice_when_ready()
    assert panel._voice_restart_pending is True
    assert voice.starts == 0

    voice.is_listening = False
    panel._on_voice_state(False)
    assert scheduled[0][0] == 100
    scheduled[0][1]()

    assert voice.starts == 1
    assert panel._voice_restart_pending is False
    panel.close()


def test_voice_button_stops_an_active_hands_free_session_between_turns(qtbot):
    panel = InteractionPanel(
        StateManager(), EventBus(), _StreamingRouter(), settings=_Settings()
    )
    qtbot.addWidget(panel)

    class Voice:
        listening_session_active = True
        is_listening = False
        stopped = False

        def stop_listening(self):
            self.stopped = True
            self.listening_session_active = False

        def start_listening(self):
            raise AssertionError("An active session should be stopped, not restarted.")

    voice = Voice()
    panel._voice = voice
    activity = []
    panel.voice_active_changed.connect(activity.append)
    panel._on_voice_state(False)
    assert panel._btn_mic.text() == "Stop"
    assert activity == [True]
    panel.toggle_voice()

    assert voice.stopped is True
    panel.close()


def test_search_button_forces_search_instead_of_local_command(
    qtbot, tmp_path, monkeypatch
):
    from jarvis.core.command_router import CommandRouter

    database.close()
    monkeypatch.setattr(database, "_db_path", lambda: tmp_path / "jarvis.db")
    router = CommandRouter()
    calls = []
    router.register_search_handler(
        lambda query: calls.append(query) or "Found sources"
    )
    panel = InteractionPanel(
        StateManager(), EventBus(), router, settings=_Settings()
    )
    qtbot.addWidget(panel)
    panel.set_input_text("hello")
    panel._btn_search.setChecked(True)
    panel._on_send()
    qtbot.waitUntil(lambda: panel._command_thread is None, timeout=5000)

    assert calls == ["hello"]
    assert panel._stream_bubble.text().startswith("Found sources")
    panel.close()
    database.close()
