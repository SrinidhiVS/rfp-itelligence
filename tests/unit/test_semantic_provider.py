from src.search.semantic import SemanticProvider


def test_semantic_provider_can_be_injected() -> None:
    provider = SemanticProvider(lambda query, text: 0.75 if query == text else 0.0)
    assert provider.score("same", "same") == 0.75
