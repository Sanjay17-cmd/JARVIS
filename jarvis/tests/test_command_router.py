"""
tests/test_command_router.py — Unit tests for the CommandRouter.
"""
import pytest
from jarvis.core.command_router import CommandRouter


@pytest.fixture
def router():
    return CommandRouter()


def test_hello_command(router):
    result = router.route("hello")
    assert "JARVIS" in result or "Hello" in result


def test_help_command_lists_commands(router):
    result = router.route("help")
    assert "hello" in result
    assert "demo" in result


def test_status_command(router):
    result = router.route("status")
    assert "operational" in result.lower() or "JARVIS" in result


def test_demo_command(router):
    result = router.route("demo")
    assert "Demo" in result or "demo" in result.lower()


def test_version_command(router):
    result = router.route("version")
    assert "0.1" in result or "JARVIS" in result


def test_unknown_command_returns_helpful_message(router):
    result = router.route("xyzzy_unknown_cmd")
    assert "xyzzy_unknown_cmd" in result or "don't recognise" in result.lower()


def test_empty_input_returns_empty(router):
    result = router.route("")
    assert result == ""


def test_case_insensitive_routing(router):
    result = router.route("HELLO")
    assert result == router.route("hello")


def test_custom_registration(router):
    @router.register("ping")
    def _ping(text: str) -> str:
        return "pong"

    assert router.route("ping") == "pong"


def test_ai_fallback_called_for_unknown(router):
    called_with = []
    router.register_ai_fallback(lambda t: (called_with.append(t), "AI reply")[1])
    result = router.route("what is the meaning of life")
    assert called_with[0].startswith("what")
    assert result == "AI reply"


def test_route_stream_forwards_builtin_response(router):
    chunks = []
    result = router.route_stream("hello", chunks.append)
    assert result == "".join(chunks)
    assert "JARVIS" in result
    assert router.has_builtin("hello")
    assert not router.has_builtin("not-a-command")


def test_route_stream_forwards_ai_chunks(router):
    chunks = []

    def stream_reply(text, on_chunk):
        on_chunk("AI ")
        on_chunk("reply")
        return "AI reply"

    router.register_ai_fallback(lambda text: "AI reply", stream_reply)
    result = router.route_stream("question", chunks.append)
    assert result == "AI reply"
    assert chunks == ["AI ", "reply"]


def test_voice_request_uses_shared_action_fallback(router):
    calls = []
    router.register_voice_fallback(
        lambda prompt, _chunk, _cancel, _reset: calls.append(prompt) or "voice action"
    )
    router.register_ai_fallback(
        lambda _text: "regular",
        cancelable_stream_handler=lambda _text, _chunk, _cancel, _reset: "regular stream",
    )

    assert router.route_stream(
        "Create a task", lambda _chunk: None, voice_request=True
    ) == "voice action"
    assert calls == ["Create a task"]


def test_disabled_voice_actions_skip_local_side_effects(router):
    invoked = []
    router._commands["danger"] = lambda _text: invoked.append(True) or "done"
    router.register_voice_fallback(
        lambda _text, _chunk, _cancel, _reset: "I can answer but won't act",
        actions_allowed=lambda: False,
    )

    assert router.route_stream(
        "danger", lambda _chunk: None, voice_request=True
    ) == "I can answer but won't act"
    assert invoked == []


@pytest.mark.parametrize(
    "command",
    ["task finish report", "done 4", "remind me in 5 minutes to stretch",
     "alarm in 10 minutes", "open notepad", "focus start"],
)
def test_mutating_chat_commands_go_through_confirmation_pipeline(router, command):
    calls = []
    router.register_ai_fallback(
        lambda prompt: calls.append(prompt) or "confirmation pending",
        cancelable_stream_handler=lambda prompt, _chunk, _cancel, _reset: (
            calls.append(prompt) or "confirmation pending"
        ),
    )

    response = router.route_stream(command, lambda _chunk: None)

    assert response == "confirmation pending"
    assert calls == [command]
    assert not router.has_builtin(command)


def test_mutating_chat_command_is_blocked_when_confirmation_service_is_missing(router):
    invoked = []
    router._commands["task"] = lambda _text: invoked.append(True) or "created"

    response = router.route_stream("task a report", lambda _chunk: None)

    assert "confirmation service is unavailable" in response
    assert invoked == []


def test_configured_ai_keyword_strips_prefix_and_forces_ai(router):
    calls = []
    router.register_ai_fallback(lambda text: calls.append(text) or "AI result")
    router.set_ai_keywords(["Friday", "Computer"])

    assert router.route("FrIdAy, explain recursion") == "AI result"
    assert calls == ["explain recursion"]
    assert router.route("Computer: search for current AI news") == "AI result"
    assert calls[-1] == "search for current AI news"
    assert not router.has_builtin("Friday, hello")


def test_all_configured_trigger_aliases_force_ai_before_local_commands(router):
    calls = []
    router.set_ai_keywords(["Friday", "Susanth"])
    router.register_ai_fallback(lambda text: calls.append(text) or "AI response")

    assert router.route("Friday, hello") == "AI response"
    assert router.route("sUsAnTh: hello") == "AI response"
    assert calls == ["hello", "hello"]


def test_custom_command_normalizes_punctuation_and_whitespace(router):
    invoked = []
    router.set_custom_commands(
        [{
            "id": "greet-team",
            "name": "Greet the team",
            "triggers": ["greet the team"],
            "aliases": [],
            "action": "greet",
            "arguments": {"name": "team"},
            "enabled": True,
            "reply": "Hello, {name}!",
        }],
        {"greet": lambda args: invoked.append(args) or "completed"},
    )

    assert router.route("  Greet,   the team! ") == "Hello, team!"
    assert invoked == [{"name": "team"}]


def test_custom_command_action_failure_is_not_reported_as_success(router):
    router.set_custom_commands(
        [{
            "id": "bad-action",
            "name": "Bad action",
            "triggers": ["bad action"],
            "aliases": [],
            "action": "bad",
            "arguments": {},
            "enabled": True,
            "reply": "This reply must not hide failure",
        }],
        {"bad": lambda _args: "❌ action failed"},
    )

    assert router.route("bad action") == "❌ action failed"


def test_response_templates_are_applied_to_builtin_interactions(router):
    router.set_responses({
        "greeting": ["Welcome back!"],
        "unsupported_command": ["No match for this request."],
    })
    assert router.route("hello") == "Welcome back!"
    assert router.route("unsupported_phrase") == "No match for this request."


def test_router_reports_when_a_builtin_response_uses_predefined_text(router):
    router.set_responses({"greeting": ["Welcome back!"]})

    assert router.route("hello") == "Welcome back!"
    assert router.last_response_is_predefined is True

    router.route("status")
    assert router.last_response_is_predefined is True


@pytest.mark.parametrize(
    "phrase",
    [
        "hi",
        "hey",
        "hi how are you",
        "how are you today",
        "good morning",
        "good evening",
    ],
)
def test_common_greetings_are_local_predefined_responses(router, phrase):
    called = []
    router.register_ai_fallback(lambda text: called.append(text) or "AI reply")

    answer = router.route(phrase)

    assert answer
    assert router.has_builtin(phrase)
    assert called == []
    assert router.last_response_is_predefined is True


def test_unknown_request_still_uses_ai_fallback_and_is_not_marked(router):
    router.register_ai_fallback(lambda _text: "AI answer")

    assert router.route("Explain a black hole") == "AI answer"
    assert router.last_response_is_predefined is False


def test_current_information_routes_to_search_handler_before_ai(router):
    calls = []
    router.register_ai_fallback(lambda _text: "AI without search")
    router.register_search_handler(lambda query: calls.append(query) or "Search result")

    assert router.route_stream("latest Python release", lambda _chunk: None) == (
        "Search result"
    )
    assert calls == ["latest Python release"]


def test_forced_search_can_search_even_for_builtin_input(router):
    router.register_search_handler(lambda query: f"searched: {query}")

    assert router.route_stream(
        "hello", lambda _chunk: None, force_search=True
    ) == "searched: hello"


def test_local_command_takes_precedence_over_automatic_search(router):
    @router.register("meeting")
    def _meeting(_text):
        return "Local reminder created"

    calls = []
    router.register_search_handler(
        lambda query: calls.append(query) or "Search result"
    )

    assert router.route_stream(
        "meeting today", lambda _chunk: None
    ) == "Local reminder created"
    assert calls == []


def test_alarm_command_requires_confirmation_pipeline(
    router, tmp_path, monkeypatch
):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from jarvis.scheduling import database

    database.close()
    monkeypatch.setattr(database, "_db_path", lambda: tmp_path / "jarvis.db")

    calls = []
    router.register_ai_fallback(
        lambda prompt: calls.append(prompt) or "Please confirm: create alarm."
    )
    answer = router.route_stream("alarm at 11:59 PM", lambda _chunk: None)

    assert answer.startswith("Please confirm:")
    assert calls == ["alarm at 11:59 PM"]
    assert router.last_response_is_predefined is False
    assert not router.has_builtin("alarm at 11:59 PM")
    assert database.execute("SELECT COUNT(*) FROM alarms").fetchone()[0] == 0


def test_ambiguous_custom_trigger_returns_actionable_error(router):
    commands = [
        {
            "id": f"ambiguous-{index}",
            "name": f"Command {index}",
            "triggers": ["same phrase"],
            "aliases": [],
            "action": "noop",
            "arguments": {},
            "enabled": True,
        }
        for index in range(2)
    ]
    router.set_custom_commands(commands, {"noop": lambda _args: "done"})
    assert router.has_builtin("same phrase")
    assert "multiple custom commands" in router.route("same phrase")
