from src.agents.providers import OpenAIModelProvider
from src.agents.settings import Settings


def test_openai_provider_requires_external_key():
    try:
        OpenAIModelProvider(Settings(openai_api_key=None))
    except RuntimeError as exc:
        assert "OPENAI_API_KEY" in str(exc)
    else:
        raise AssertionError("provider accepted missing key")
