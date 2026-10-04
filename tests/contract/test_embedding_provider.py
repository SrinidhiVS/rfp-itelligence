from src.search.embeddings import DeterministicEmbeddingProvider


def test_deterministic_provider_has_stable_dimensions():
    provider = DeterministicEmbeddingProvider(dimension=8)
    first = provider.embed(["deadline"])
    second = provider.embed(["deadline"])
    assert first == second
    assert len(first[0]) == 8
