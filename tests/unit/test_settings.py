import src.agents.settings as settings_module
from src.agents.settings import Settings


def test_settings_keep_provider_values_external(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    settings = Settings.from_env()
    assert settings.openai_model == "test-model"
    assert settings.openai_api_key is None or isinstance(settings.openai_api_key, str)


def test_settings_load_dotenv_and_preserve_environment_precedence(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "LANGSMITH_API_KEY=dotenv-key\n"
        "LANGSMITH_PROJECT=dotenv-project\n"
        "OPENAI_MODEL=dotenv-model\n"
        "RFP_TRACE=false\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings_module, "ENV_FILE", env_file)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.setenv("LANGSMITH_PROJECT", "environment-project")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("RFP_TRACE", raising=False)

    settings = Settings.from_env()

    assert settings.langsmith_api_key == "dotenv-key"
    assert settings.langsmith_project == "environment-project"
    assert settings.openai_model == "dotenv-model"
    assert settings.trace_enabled is False
