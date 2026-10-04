import sys

from src import cli as root_cli
from src.search.embeddings import DeterministicEmbeddingProvider
from src.search.models import IndexRecord
from src.search.vector_store import VectorStore


def test_root_cli_forwards_vector_index(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["src.cli", "vector-index"])
    monkeypatch.setattr(root_cli, "search_main", lambda: 7)

    assert root_cli.main() == 7


def test_chroma_build_leaves_legacy_json_files_untouched(tmp_path):
    legacy_data = tmp_path / "search-vectors.json"
    legacy_manifest = tmp_path / "search-vectors.json.manifest.json"
    legacy_data.write_bytes(b'{"legacy": true}')
    legacy_manifest.write_bytes(b'{"legacy_manifest": true}')
    before = legacy_data.read_bytes(), legacy_manifest.read_bytes()
    provider = DeterministicEmbeddingProvider(8)
    record = IndexRecord(
        record_id="r1",
        chunk_id="r1",
        scope_id="Bid1:rfp.pdf",
        content_fingerprint="fp1",
        text="submission deadline",
        bid_id="Bid1",
        source_file="rfp.pdf",
        page_number=1,
        section_title=None,
        doc_type="rfp",
        addendum_number=None,
        document_date=None,
        source_locator={"relative_path": "rfp.pdf", "page_number": 1},
    )

    result = VectorStore(tmp_path / "chroma").update_from_records([record], provider)

    assert result["failed"] == 0
    assert (legacy_data.read_bytes(), legacy_manifest.read_bytes()) == before