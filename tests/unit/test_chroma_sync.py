from src.search.chroma_sync import sync_chroma_index
from src.search.embeddings import DeterministicEmbeddingProvider
from src.search.index import IndexService
from src.search.storage import CorpusStore
from src.search.vector_store import VectorStore


def _request(bid_id, source, record_id, text):
    return {
        "bid_id": bid_id,
        "source_manifest": [{"relative_path": source}],
        "chunks": [{
            "chunk_id": record_id,
            "text": text,
            "bid_id": bid_id,
            "source_file": source,
            "page_number": 1,
            "doc_type": "rfp",
            "source_locator": {"relative_path": source, "page_number": 1},
        }],
    }


def test_sync_updates_only_new_bid_scopes_and_preserves_existing_vectors(tmp_path, monkeypatch):
    corpus_store = CorpusStore(tmp_path / "corpus.json")
    vector_store = VectorStore(tmp_path / "chroma")
    provider = DeterministicEmbeddingProvider(8)
    monkeypatch.setenv("RFP_CHROMA_PATH", str(vector_store.path))
    indexer = IndexService(corpus_store)
    indexer.update(_request("Bid1", "one.pdf", "one", "first bid deadline"))

    first = sync_chroma_index(corpus_store, provider)
    first_records, _ = vector_store.load(provider.config)
    first_vector = next(record.vector for record in first_records if record.bid_id == "Bid1")

    indexer.update(_request("Bid2", "two.pdf", "two", "second bid deadline"))
    second = sync_chroma_index(corpus_store, provider)
    records, _ = vector_store.load(provider.config)

    assert first["embedded"] == 1
    assert second["embedded"] == 1
    assert second["unchanged"] == 1
    assert {record.bid_id for record in records} == {"Bid1", "Bid2"}
    assert next(record.vector for record in records if record.bid_id == "Bid1") == first_vector