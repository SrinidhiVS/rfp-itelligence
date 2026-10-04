from src.search.models import IndexRecord
from src.search.embeddings import DeterministicEmbeddingProvider
from src.search.vector_store import VectorStore


def _record(bid_id, record_id, text):
    return IndexRecord(
        record_id=record_id,
        chunk_id=record_id,
        scope_id=f"{bid_id}:shared/rfp.pdf",
        content_fingerprint=f"fingerprint-{text}",
        text=text,
        bid_id=bid_id,
        source_file="rfp.pdf",
        page_number=2,
        section_title="Submission",
        doc_type="rfp",
        addendum_number=None,
        document_date=None,
        source_locator={"relative_path": "shared/rfp.pdf", "page_number": 2},
        content_kind="text",
    )


def test_identical_relative_paths_remain_bid_isolated_during_update_and_delete(tmp_path):
    provider = DeterministicEmbeddingProvider(8)
    store = VectorStore(tmp_path / "vectors.json")
    bid1 = _record("Bid1", "bid1-r1", "bid one original")
    bid2 = _record("Bid2", "bid2-r1", "bid two original")
    store.update_from_records([bid1, bid2], provider)
    initial_records, initial_manifest = store.load(provider.config)
    bid2_original = next(record.__dict__.copy() for record in initial_records if record.bid_id == "Bid2")
    bid2_fingerprint = initial_manifest.scope_fingerprints["Bid2:shared/rfp.pdf"]

    store.update_from_records([_record("Bid1", "bid1-r2", "bid one changed"), bid2], provider)
    after_update, _ = store.load(provider.config)
    assert next(record.__dict__ for record in after_update if record.bid_id == "Bid2") == bid2_original

    result = store.update_from_records([bid2], provider)
    after_delete, manifest_after_delete = store.load(provider.config)
    assert result["removed"] == 1
    assert [record.bid_id for record in after_delete] == ["Bid2"]
    assert after_delete[0].__dict__ == bid2_original
    assert manifest_after_delete.scope_fingerprints == {"Bid2:shared/rfp.pdf": bid2_fingerprint}


def test_persistence_failure_restores_vector_records_and_manifest(tmp_path, monkeypatch):
    import src.search.vector_store as vector_store_module

    provider = DeterministicEmbeddingProvider(8)
    store = VectorStore(tmp_path / "chroma")
    original = _record("Bid1", "r1", "original evidence")
    store.update_from_records([original], provider)
    original_records, original_manifest = store.load(provider.config)
    changed = _record("Bid1", "r2", "changed evidence")
    failed_once = False
    replace = vector_store_module.os.replace

    def fail_manifest_once(source, destination):
        nonlocal failed_once
        if destination == store.manifest_path and not failed_once:
            failed_once = True
            raise OSError("injected manifest write failure")
        return replace(source, destination)

    monkeypatch.setattr(vector_store_module.os, "replace", fail_manifest_once)
    result = store.update_from_records([changed], provider)

    assert result["failed"] == 1
    assert failed_once
    assert "injected manifest write failure" in result["diagnostics"][0]
    recovered_records, recovered_manifest = VectorStore(store.path).load(provider.config)
    assert [item.__dict__ for item in recovered_records] == [item.__dict__ for item in original_records]
    assert recovered_manifest == original_manifest