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
    assert router.last_response_is_predefined is False


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
