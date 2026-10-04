import json
from pathlib import Path

from src.extraction.extractor import StructuredExtractor
from src.extraction.source_diagnostics import diagnostic_for_source


def test_declared_source_failure_fixture_preserves_usable_source():
    fixture = json.loads(Path("tests/fixtures/structured_extraction/source-failure.json").read_text(encoding="utf-8"))
    record = StructuredExtractor().extract(fixture["bid_id"], [{"record": {"source_file": "usable.html", "page_number": None, "source_locator": "deadline", "bid_id": fixture["bid_id"], "text": "submission deadline October 20"}}], diagnostics=[diagnostic_for_source("broken.pdf", "unreadable page")])
    assert record.fields["Due Date"].value
    assert record.diagnostics[0].source_file == "broken.pdf"
