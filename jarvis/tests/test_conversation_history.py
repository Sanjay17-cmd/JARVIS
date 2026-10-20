from jarvis.scheduling import database


def test_conversation_history_round_trip_and_limit(tmp_path, monkeypatch):
    database.close()
    monkeypatch.setattr(database, "_db_path", lambda: tmp_path / "jarvis.db")
    try:
        database.save_conversation_message("user", "hello", 1.0)
        database.save_conversation_message("assistant", "hi", 2.0)

        assert database.load_conversation_history() == [
            {"role": "user", "content": "hello", "created_at": 1.0},
            {"role": "assistant", "content": "hi", "created_at": 2.0},
        ]
        assert database.load_conversation_history(limit=1) == [
            {"role": "assistant", "content": "hi", "created_at": 2.0}
        ]
    finally:
        database.close()


def test_conversation_history_rejects_invalid_role():
    try:
        database.save_conversation_message("system", "not allowed", 1.0)
    except ValueError:
        pass
    else:
        raise AssertionError("Expected an invalid conversation role to be rejected")
