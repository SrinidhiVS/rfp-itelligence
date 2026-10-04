from pathlib import Path

from src.search.index import IndexService
from src.search.storage import CorpusStore


def chunk(bid: str, path: str, text: str, chunk_id: str) -> dict:
    return {"chunk_id": chunk_id, "text": text, "source_file": path, "source_locator": {"relative_path": path}, "bid_id": bid}


def test_index_is_idempotent_and_scoped(tmp_path: Path) -> None:
    service = IndexService(CorpusStore(tmp_path / "index.json"))
    bid1 = {"bid_id": "Bid1", "chunks": [chunk("Bid1", "a.pdf", "deadline 1", "a")]}
    bid2 = {"bid_id": "Bid2", "chunks": [chunk("Bid2", "b.pdf", "deadline 2", "b")]}
    assert service.update(bid1)["indexed"] == 1
    assert service.update(bid2)["indexed"] == 1
    assert service.update(bid1)["skipped"] == 1
    records = service.records()
    assert {record.bid_id for record in records} == {"Bid1", "Bid2"}


def test_changed_file_replaces_scope_and_full_rebuild_removes_other_scope(tmp_path: Path) -> None:
    service = IndexService(CorpusStore(tmp_path / "index.json"))
    service.update({"bid_id": "Bid1", "chunks": [chunk("Bid1", "a.pdf", "old", "a")]})
    service.update({"bid_id": "Bid1", "chunks": [chunk("Bid1", "a.pdf", "new", "a2")]})
    assert [record.text for record in service.records()] == ["new"]
    service.update({"bid_id": "Bid2", "chunks": [chunk("Bid2", "b.pdf", "other", "b")]})
    service.update({"bid_id": "Bid1", "chunks": [chunk("Bid1", "a.pdf", "rebuilt", "a3")]}, full_rebuild=True)
    assert [record.bid_id for record in service.records()] == ["Bid1"]
