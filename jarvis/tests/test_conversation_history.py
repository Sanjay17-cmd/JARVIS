from jarvis.scheduling import database
import pytest
import time


@pytest.fixture(autouse=True)
def isolated_conversation_db(tmp_path, monkeypatch):
    database.close()
    monkeypatch.setenv("APPDATA", str(tmp_path))
    database._conn = None
    yield
    database.close()
    database._conn = None


def test_conversation_history_round_trip_and_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "_db_path", lambda: tmp_path / "jarvis.db")
    database.save_conversation_message("user", "hello", 1.0)
    database.save_conversation_message("assistant", "hi", 2.0)

    assert database.load_conversation_history() == [
        {"role": "user", "content": "hello", "created_at": 1.0},
        {"role": "assistant", "content": "hi", "created_at": 2.0},
    ]
    assert database.load_conversation_history(limit=1) == [
        {"role": "assistant", "content": "hi", "created_at": 2.0}
    ]


def test_conversation_history_persists_assistant_model_label():
    database.save_conversation_message(
        "assistant",
        "Hello",
        2.0,
        model_label="openrouter · provider/model",
    )

    assert database.load_conversation_history() == [
        {
            "role": "assistant",
            "content": "Hello",
            "created_at": 2.0,
            "model_label": "openrouter · provider/model",
        }
    ]


def test_new_conversations_keep_separate_messages_and_restore_active_chat():
    first = database.create_conversation("First", activate=True)
    database.save_conversation_message("user", "first chat", time.time())
    second = database.create_conversation("Second", activate=True)
    database.save_conversation_message("user", "second chat", time.time())

    assert first != second
    assert database.load_conversation_history(conversation_id=first)[0]["content"] == "first chat"
    assert database.load_conversation_history(conversation_id=second)[0]["content"] == "second chat"
    assert database.active_conversation_id() == second
    database.set_active_conversation(first)
    assert database.active_conversation_id() == first


def test_conversation_history_rejects_invalid_role():
    try:
        database.save_conversation_message("system", "not allowed", 1.0)
    except ValueError:
        pass
    else:
        raise AssertionError("Expected an invalid conversation role to be rejected")
