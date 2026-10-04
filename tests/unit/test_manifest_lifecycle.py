from pathlib import Path

from src.search.index import IndexService
from src.search.storage import CorpusStore


def test_manifest_only_deleted_scope_is_removed(tmp_path: Path) -> None:
    service = IndexService(CorpusStore(tmp_path / "index.json"))
    service.update({"bid_id": "Bid1", "source_manifest": [{"relative_path": "empty.pdf"}], "chunks": []})
    service.update({"bid_id": "Bid1", "source_manifest": [], "chunks": []})
    assert service.report()["source_manifest"] == []
