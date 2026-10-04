from src.search.embedding_models import EmbeddingConfig


def test_local_embedding_config_contains_no_secret_fields():
    config = EmbeddingConfig()
    assert not hasattr(config, "api_key")
    assert config.provider == "sentence-transformers"
