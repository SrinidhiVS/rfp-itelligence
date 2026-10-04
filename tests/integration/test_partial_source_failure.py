from src.extraction.extractor import StructuredExtractor
from src.extraction.source_diagnostics import diagnostic_for_source


def test_usable_fields_survive_recoverable_source_failure():
    diagnostic = diagnostic_for_source("broken.pdf", "empty page")
    record = StructuredExtractor().extract("Bid1", [{"record": {"source_file": "bid.html", "page_number": None, "source_locator": "deadline", "bid_id": "Bid1", "text": "deadline October 20"}}], diagnostics=[diagnostic])
    assert record.fields["Due Date"].value is not None
    assert record.diagnostics[0].source_file == "broken.pdf"
