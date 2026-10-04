from pathlib import Path

from src.ingestion.pipeline import IngestionPipeline


def test_fixture_failures_are_visible() -> None:
    root = Path(__file__).resolve().parents[1] / "fixtures" / "partial-bid"
    report = IngestionPipeline().process(root)
    assert report.status == "incomplete"
    assert len(report.files) == 3
    assert report.diagnostics


def test_malformed_metadata_keeps_usable_html_when_neighbor_file_fails(tmp_path: Path) -> None:
    (tmp_path / "usable.html").write_text(
        '<html><head><link rel="canonical" href="/relative"></head><body><h1>Usable Bid</h1></body></html>',
        encoding="utf-8",
    )
    (tmp_path / "broken.pdf").write_bytes(b"not a PDF")

    report = IngestionPipeline().process(tmp_path, bid_id="partial-metadata")
    html_document = next(document for document in report.files if document.detected_format == "html")
    pdf_document = next(document for document in report.files if document.file_name == "broken.pdf")

    assert html_document.status == "parsed"
    assert "Usable Bid" in html_document.pages[0].normalized_text
    assert any(item.code == "html_metadata_invalid" for item in html_document.diagnostics)
    assert pdf_document.status == "failed"
    assert report.status == "incomplete"
