import logging
from pathlib import Path

from src.ingestion.models import NormalizedPage, ProcessingDiagnostic
from src.ingestion.pipeline import IngestionPipeline


def test_failure_event_is_source_located_and_excludes_raw_content(tmp_path: Path, monkeypatch, caplog) -> None:
    import src.ingestion.pipeline as pipeline_module

    nested = tmp_path / "nested"
    nested.mkdir()
    source = nested / "case.html"
    source.write_text("<html><body><h1>Bid</h1></body></html>", encoding="utf-8")
    failure = ProcessingDiagnostic(
        "diag-1",
        "page",
        "page_text_extraction_failure",
        "PRIVATE-SOURCE-SENTINEL",
        source_locator={"relative_path": "case.html", "page_number": 3},
    )
    page = NormalizedPage("page-3", "document-1", 3, None, None, None, status="partial", diagnostics=[failure])
    monkeypatch.setattr(pipeline_module, "parse_source", lambda *_args: [page])
    caplog.set_level(logging.INFO, logger="rfp_ingestion")

    IngestionPipeline().process(tmp_path, bid_id="Bid-Log")

    output = caplog.text
    assert "processing_failure" in output
    assert "nested/case.html" in output
    assert "page_text_extraction_failure" in output
    assert "page_number" in output and "3" in output
    assert "operation" in output
    assert "recovery_status" in output and "partial" in output
    assert "PRIVATE-SOURCE-SENTINEL" not in output
    assert failure.recovery_status == "partial"
