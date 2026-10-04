import pytest

from src.search.models import IndexRecord
from src.search.embedding_models import VectorRecord
from src.search.embeddings import DeterministicEmbeddingProvider
from src.search.vector_store import VectorStore


def test_scope_manifest_records_fingerprints(tmp_path):
    provider = DeterministicEmbeddingProvider(8)
    record = VectorRecord("r", provider.embed(["text"])[0], "scope-a", "fingerprint-a", "Bid1", "a.pdf", 1, {}, "text")
    store = VectorStore(tmp_path / "vectors.json")
    store.save([record], provider.config, {"scope-a": "fingerprint-a"})
    _, manifest = store.load(provider.config)
    assert manifest.scope_fingerprints == {"scope-a": "fingerprint-a"}


class RecordingEmbeddingProvider(DeterministicEmbeddingProvider):
    def __init__(self, dimension=8):
        super().__init__(dimension)
        self.inputs = []

    def embed(self, texts):
        self.inputs.extend(texts)
        return super().embed(texts)


def _index_record(bid_id, relative_path, record_id, text, section_title="Requirements"):
    return IndexRecord(
        record_id=record_id,
        chunk_id=record_id,
        scope_id=f"{bid_id}:{relative_path}",
        content_fingerprint=f"fingerprint-{text}",
        text=text,
        bid_id=bid_id,
        source_file=relative_path.rsplit("/", 1)[-1],
        page_number=1,
        section_title=section_title,
        doc_type="rfp",
        addendum_number=None,
        document_date=None,
        source_locator={"relative_path": relative_path, "page_number": 1},
        content_kind="text",
    )


def test_vector_index_incremental_lifecycle_embeds_only_new_or_changed_scopes(tmp_path):
    provider = RecordingEmbeddingProvider()
    store = VectorStore(tmp_path / "vectors.json")
    initial = [
        _index_record("Bid1", "rfp.pdf", "a-old", "alpha old"),
        _index_record("Bid1", "pricing.pdf", "b-stable", "beta stable"),
        _index_record("Bid2", "rfp.pdf", "other-bid", "other bid"),
    ]

    first = store.update_from_records(initial, provider)
    original_records, original_manifest = store.load(provider.config)
    original_by_id = {record.record_id: record.__dict__.copy() for record in original_records}
    assert first["embedded"] == 3
    assert first["unchanged"] == 0

    unchanged = store.update_from_records(initial, provider)
    records_after_unchanged, _ = store.load(provider.config)
    assert unchanged["unchanged"] == 3
    assert unchanged["embedded"] == 0
    assert len(provider.inputs) == 3
    records_by_id = {record.record_id: record.__dict__.copy() for record in records_after_unchanged}
    assert records_by_id.keys() == original_by_id.keys()
    for record_id, current in records_by_id.items():
        original = original_by_id[record_id]
        assert current.pop("vector") == pytest.approx(original["vector"])
        original_without_vector = {key: value for key, value in original.items() if key != "vector"}
        assert current == original_without_vector

    changed_input = [
        _index_record("Bid1", "rfp.pdf", "a-new", "alpha changed"),
        initial[1],
        initial[2],
    ]
    changed = store.update_from_records(changed_input, provider)
    changed_records, changed_manifest = store.load(provider.config)
    assert changed["embedded"] == 1
    assert changed["replaced"] == 1
    assert len(provider.inputs) == 4
    assert "a-old" not in {record.record_id for record in changed_records}
    assert "a-new" in {record.record_id for record in changed_records}
    assert changed_manifest.scope_fingerprints["Bid1:rfp.pdf"] != original_manifest.scope_fingerprints["Bid1:rfp.pdf"]

    deleted = store.update_from_records(changed_input[1:], provider)
    deleted_records, deleted_manifest = store.load(provider.config)
    assert deleted["removed"] == 1
    assert deleted["unchanged"] == 2
    assert len(provider.inputs) == 4
    assert "Bid1:rfp.pdf" not in deleted_manifest.scope_fingerprints
    assert {record.bid_id for record in deleted_records} == {"Bid1", "Bid2"}


def test_empty_scope_is_skipped_without_embedding(tmp_path):
    provider = RecordingEmbeddingProvider()
    store = VectorStore(tmp_path / "vectors.json")
    empty = _index_record("Bid1", "empty.pdf", "empty", "   ")

    result = store.update_from_records([empty], provider)

    assert result["embedded"] == 0
    assert result["skipped_empty"] == 1
    assert result["failed"] == 0
    assert provider.inputs == []


def test_full_rebuild_reports_replaced_and_removed_scopes(tmp_path):
    provider = RecordingEmbeddingProvider()
    store = VectorStore(tmp_path / "chroma")
    initial = [
        _index_record("Bid1", "rfp.pdf", "bid1-record", "bid one"),
        _index_record("Bid2", "rfp.pdf", "bid2-record", "bid two"),
    ]
    store.update_from_records(initial, provider)

    result = store.update_from_records([initial[0]], provider, full_rebuild=True)

    records, manifest = store.load(provider.config)
    assert result["replaced"] == 1
    assert result["removed"] == 1
    assert [record.record_id for record in records] == ["bid1-record"]
    assert set(manifest.scope_fingerprints) == {"Bid1:rfp.pdf"}


def test_incompatible_embedding_dimension_preserves_existing_index(tmp_path):
    original_provider = RecordingEmbeddingProvider(8)
    store = VectorStore(tmp_path / "chroma")
    record = _index_record("Bid1", "rfp.pdf", "r1", "original")
    store.update_from_records([record], original_provider)
    original_records, original_manifest = store.load(original_provider.config)

    incompatible_provider = RecordingEmbeddingProvider(16)
    result = store.update_from_records([record], incompatible_provider)

    assert result["failed"] == 1
    current_records, current_manifest = VectorStore(store.path).load(original_provider.config)
    assert [item.__dict__ for item in current_records] == [item.__dict__ for item in original_records]
    assert current_manifest == original_manifest


def test_embedding_failure_preserves_existing_index_and_manifest(tmp_path):
    provider = RecordingEmbeddingProvider()
    store = VectorStore(tmp_path / "chroma")
    original = _index_record("Bid1", "rfp.pdf", "r1", "original")
    store.update_from_records([original], provider)
    original_records, original_manifest = store.load(provider.config)

    class FailingProvider:
        config = provider.config

        def embed(self, texts):
            raise RuntimeError("injected embedding failure")

    result = store.update_from_records(
        [_index_record("Bid1", "rfp.pdf", "r2", "changed")],
        FailingProvider(),
    )

    assert result["failed"] == 1
    assert "injected embedding failure" in result["diagnostics"][0]
    current_records, current_manifest = VectorStore(store.path).load(provider.config)
    assert [item.__dict__ for item in current_records] == [item.__dict__ for item in original_records]
    assert current_manifest == original_manifest
