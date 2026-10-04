import chromadb
import pytest

from src.search.embedding_models import EmbeddingConfig, VectorRecord
from src.search.embeddings import DeterministicEmbeddingProvider
from src.search.vector_store import VectorIndexError, VectorStore


def test_vector_store_round_trip_and_manifest(tmp_path):
    provider = DeterministicEmbeddingProvider(8)
    record = VectorRecord("r1", provider.embed(["deadline"])[0], "scope", "fingerprint", "Bid1", "rfp.pdf", 1, {}, "deadline")
    store = VectorStore(tmp_path / "chroma")
    store.save([record], provider.config, {"scope": "fingerprint"})

    reopened = VectorStore(tmp_path / "chroma")
    records, manifest = reopened.load(provider.config)

    collection = chromadb.PersistentClient(path=str(tmp_path / "chroma")).get_collection("rfp_passages")
    persisted = collection.get(ids=["r1"], include=["documents", "metadatas", "embeddings"])
    assert records[0].record_id == "r1"
    assert records[0].vector == pytest.approx(provider.embed(["deadline"])[0])
    assert manifest.dimension == 8
    assert persisted["ids"] == ["r1"]
    assert persisted["documents"] == ["deadline"]
    assert persisted["metadatas"][0]["bid_id"] == "Bid1"


def test_vector_store_round_trips_nested_locator_and_optional_metadata(tmp_path):
    provider = DeterministicEmbeddingProvider(8)
    record = VectorRecord(
        "r1", provider.embed(["deadline"])[0], "scope", "fingerprint", "Bid1",
        "rfp.pdf", 1, {"relative_path": "rfp.pdf", "page_number": 1}, "deadline",
        section_title="Submission", content_kind="table",
    )
    store = VectorStore(tmp_path / "chroma")
    store.save([record], provider.config, {"scope": "fingerprint"})

    records, _ = store.load(provider.config)

    assert records[0].section_title == "Submission"
    assert records[0].content_kind == "table"

    assert records[0].source_locator == {"relative_path": "rfp.pdf", "page_number": 1}
    assert records[0].addendum_number is None
    metadata = chromadb.PersistentClient(path=str(tmp_path / "chroma")).get_collection("rfp_passages").get(
        ids=["r1"], include=["metadatas"]
    )["metadatas"][0]
    assert "addendum_number" not in metadata


def test_vector_store_rejects_incompatible_embedding_configuration(tmp_path):
    provider = DeterministicEmbeddingProvider(8)
    record = VectorRecord("r1", provider.embed(["deadline"])[0], "scope", "fingerprint", "Bid1", "rfp.pdf", 1, {}, "deadline")
    store = VectorStore(tmp_path / "chroma")
    store.save([record], provider.config, {"scope": "fingerprint"})

    with pytest.raises(VectorIndexError, match="incompatible"):
        store.load(EmbeddingConfig(dimension=16))
