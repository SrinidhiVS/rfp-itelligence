from pathlib import Path

from src.ingestion.pipeline import IngestionPipeline


def test_unseen_file_names_require_no_special_case(tmp_path: Path) -> None:
    (tmp_path / "portal-summary.htm").write_text("<html><body><h2>Bid Information</h2><p>Terms</p></body></html>", encoding="utf-8")
    report = IngestionPipeline().process(tmp_path, bid_id="unseen")
    assert report.status == "complete"
    assert report.files[0].doc_type == "bid_page"
    assert report.chunks[0].source_file == "portal-summary.htm"
