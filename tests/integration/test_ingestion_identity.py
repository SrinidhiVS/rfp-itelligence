from pathlib import Path

from src.ingestion.pipeline import IngestionPipeline


def test_pipeline_populates_bid_and_filename_on_pages_and_chunks(tmp_path: Path) -> None:
    nested = tmp_path / "documents"
    nested.mkdir()
    source = nested / "generic.html"
    source.write_text(
        "<html><body><h1>Bid Notice</h1><p>Submission deadline is October 20.</p></body></html>",
        encoding="utf-8",
    )

    report = IngestionPipeline().process(tmp_path, bid_id="Bid-Identity")

    assert report.pages
    assert report.chunks
    assert all(page.bid_id == "Bid-Identity" for page in report.pages)
    assert all(page.file_name == "generic.html" for page in report.pages)
    assert all(chunk.bid_id == "Bid-Identity" for chunk in report.chunks)
    assert all(chunk.file_name == "generic.html" for chunk in report.chunks)
    assert all(chunk.source_file == chunk.file_name for chunk in report.chunks)


def test_pipeline_prefers_explicit_content_addendum_number(tmp_path: Path) -> None:
    source = tmp_path / "Addendum 1 RFP.html"
    source.write_text(
        "<html><body><h1>ADDENDUM NO. 2 TO THE REQUEST FOR PROPOSAL</h1></body></html>",
        encoding="utf-8",
    )

    document = IngestionPipeline().process(tmp_path, bid_id="classification-bid").files[0]

    assert document.doc_type == "addendum"
    assert document.addendum_number == 2
    assert document.classification is not None
    assert document.classification.status == "classified"
    assert document.pages[0].doc_type == "addendum"
    assert document.pages[0].addendum_number == 2
