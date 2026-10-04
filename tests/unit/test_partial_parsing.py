from pathlib import Path

import pymupdf

from src.ingestion.pipeline import IngestionPipeline


def test_partial_folder_keeps_readable_files(tmp_path: Path) -> None:
    (tmp_path / "valid.html").write_text("<html><body><p>Readable</p></body></html>", encoding="utf-8")
    (tmp_path / "bad.pdf").write_bytes(b"invalid")
    report = IngestionPipeline().process(tmp_path)
    assert any(chunk.text == "Readable" for chunk in report.chunks)
    assert report.status == "incomplete"


def test_partially_parseable_pdf_keeps_readable_page_and_locates_empty_page(tmp_path: Path) -> None:
    source = tmp_path / "mixed-pages.pdf"
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "Submission deadline: November 9, 2026")
    document.new_page()
    document.save(source)
    document.close()

    report = IngestionPipeline().process(tmp_path, bid_id="PartialPages")

    assert report.status == "incomplete"
    assert any("November 9, 2026" in chunk.text for chunk in report.chunks)
    assert [page.status for page in report.pages] == ["parsed", "empty"]
    diagnostic = next(item for item in report.diagnostics if item.code == "empty_page")
    assert diagnostic.scope == "page"
    assert diagnostic.source_locator["page_number"] == 2
    assert diagnostic.recovery_status == "partial"
