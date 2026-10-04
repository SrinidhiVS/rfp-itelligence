from types import SimpleNamespace

from src.agents.providers import DeterministicModelProvider, OllamaModelProvider, configured_provider
from src.agents.settings import Settings


def test_provider_boundary_has_deterministic_offline_fallback():
    provider = configured_provider(Settings(openai_api_key=None))
    assert isinstance(provider, DeterministicModelProvider)
    result = provider.extract_fields([], ["deadline"])
    assert result.values == {}
    assert result.usage.availability == "unavailable"


def test_openai_provider_returns_reported_token_usage(monkeypatch):
    usage = SimpleNamespace(prompt_tokens=11, completion_tokens=7, total_tokens=18)
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"deadline": "2026-10-10"}'))],
        usage=usage,
    )

    class FakeOpenAI:
        def __init__(self, api_key):
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=lambda **kwargs: response)
            )

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    from src.agents.providers import OpenAIModelProvider

    result = OpenAIModelProvider(Settings(openai_api_key="test-key")).extract_fields(
        [], ["deadline"]
    )
    assert result.values == {"deadline": "2026-10-10"}
    assert result.usage.availability == "reported"
    assert (result.usage.input_tokens, result.usage.output_tokens, result.usage.total_tokens) == (11, 7, 18)


def test_openai_provider_keeps_partial_usage_explicit(monkeypatch):
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))],
        usage=SimpleNamespace(prompt_tokens=4, completion_tokens=None, total_tokens=None),
    )

    class FakeOpenAI:
        def __init__(self, api_key):
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=lambda **kwargs: response)
            )

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    from src.agents.providers import OpenAIModelProvider

    result = OpenAIModelProvider(Settings(openai_api_key="test-key")).extract_fields([], ["deadline"])
    assert result.usage.input_tokens == 4
    assert result.usage.output_tokens is None
    assert result.usage.total_tokens is None


def test_openai_settings_are_externalized(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    settings = Settings.from_env()
    assert settings.openai_api_key == "test-key"
    assert settings.openai_model == "test-model"


def test_ollama_provider_uses_configured_openai_compatible_endpoint(monkeypatch):
    usage = SimpleNamespace(prompt_tokens=13, completion_tokens=8, total_tokens=21)
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"answer":"Bid1 deadline is October 10, 2026."}'))],
        usage=usage,
    )
    calls = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            calls["client"] = kwargs
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=lambda **kwargs: calls.update(request=kwargs) or response)
            )

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    settings = Settings(
        model_provider="ollama",
        ollama_model="qwen2.5:3b",
        ollama_base_url="http://localhost:11434/",
    )
    provider = configured_provider(settings)
    result = provider.generate_report(
        "When is the deadline?",
        [{"text": "Bid1: submission deadline is October 10, 2026."}],
        "Bid1: submission deadline is October 10, 2026.",
    )

    assert isinstance(provider, OllamaModelProvider)
    assert calls["client"] == {"base_url": "http://localhost:11434/v1", "api_key": "ollama"}
    assert calls["request"]["model"] == "qwen2.5:3b"
    assert calls["request"]["response_format"] == {"type": "json_object"}
    assert result.values["answer"] == "Bid1 deadline is October 10, 2026."
    assert result.usage.provider == "ollama"
    assert result.usage.total_tokens == 21


def test_ollama_provider_selection_is_read_from_environment(monkeypatch):
    monkeypatch.setenv("RFP_MODEL_PROVIDER", "ollama")
    monkeypatch.setenv("RFP_OLLAMA_MODEL", "qwen2.5:3b")
    monkeypatch.setenv("RFP_OLLAMA_BASE_URL", "http://localhost:11434/v1")
    settings = Settings.from_env()
    assert settings.model_provider == "ollama"
    assert settings.ollama_model == "qwen2.5:3b"
    assert settings.ollama_base_url == "http://localhost:11434/v1"
