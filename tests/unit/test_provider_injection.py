from src.agents.providers import DeterministicModelProvider


def test_injected_provider_contract_is_callable():
    provider = DeterministicModelProvider()
    assert callable(provider.extract_fields)
