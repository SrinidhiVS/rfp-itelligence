from src.search.embedding_models import VectorRecord
from src.search.embeddings import DeterministicEmbeddingProvider
from src.search.vector_store import VectorStore


def test_embedding_acceptance_manifest_and_metadata(tmp_path):
    provider = DeterministicEmbeddingProvider(8)
    record = VectorRecord("r", provider.embed(["deadline"])[0], "scope", "fingerprint", "Bid1", "rfp.pdf", 1, {"section": "deadline"}, "deadline")
    store = VectorStore(tmp_path / "chroma")
    store.save([record], provider.config, {"scope": "fingerprint"})
    records, manifest = store.load(provider.config)
    assert manifest.model_name == "deterministic"
    assert records[0].source_file == "rfp.pdf"
