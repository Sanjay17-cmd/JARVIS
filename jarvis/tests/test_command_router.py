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
