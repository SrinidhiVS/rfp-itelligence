from pathlib import Path

from src.ingestion.pipeline import IngestionPipeline


def test_document_metadata_is_inherited_by_pages_and_chunks(tmp_path: Path) -> None:
    source = tmp_path / "Addendum 2.html"
    source.write_text("<html><body><h1>2026-12-01</h1><p>Deadline</p></body></html>", encoding="utf-8")
    report = IngestionPipeline().process(tmp_path, bid_id="bid")
    document = report.files[0]
    assert document.addendum_number == 2
    assert report.pages[0].doc_type == "addendum"
    assert report.pages[0].addendum_number == 2
    assert report.pages[0].document_date == "2026-12-01"
    assert report.chunks[0].addendum_number == 2
    assert report.chunks[0].document_date == "2026-12-01"
