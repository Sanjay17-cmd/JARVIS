from jarvis.config.api_keys import load_api_environment


def test_dotenv_loads_provider_keys_without_overriding_process_environment(
    tmp_path, monkeypatch
):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "GEMINI_API_KEY=local-secret\nOPENAI_API_KEY=other-secret\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "already-configured")

    assert load_api_environment(env_file)
    import os
    assert os.environ["GEMINI_API_KEY"] == "local-secret"
    assert os.environ["OPENAI_API_KEY"] == "already-configured"
