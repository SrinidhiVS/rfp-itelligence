from pathlib import Path

from src.ingestion.pipeline import IngestionPipeline


ROOT = Path(__file__).resolve().parents[2]


def test_supplied_bid_folders_are_processed() -> None:
    bid1 = IngestionPipeline().process(ROOT / "Initial_docs" / "Bid1")
    bid2 = IngestionPipeline().process(ROOT / "Initial_docs" / "Bid2")
    assert bid1.status == "incomplete"
    assert bid2.status == "complete"
    assert bid1.discovered_file_count == 4
    assert bid2.discovered_file_count == 5
    assert bid1.chunks
    assert bid2.chunks
    assert bid1.diagnostics


def test_invalid_and_unsupported_files_are_visible(tmp_path: Path) -> None:
    (tmp_path / "valid.html").write_text("<html><body><h1>Bid</h1><p>Deadline</p></body></html>", encoding="utf-8")
    (tmp_path / "broken.pdf").write_bytes(b"not a pdf")
    (tmp_path / "notes.txt").write_text("unsupported", encoding="utf-8")
    report = IngestionPipeline().process(tmp_path, bid_id="test-bid")
    assert report.status == "incomplete"
    assert len(report.files) == 3
    assert any(item.status == "failed" for item in report.files)
    assert any(item.status == "unsupported" for item in report.files)
    assert report.diagnostics
