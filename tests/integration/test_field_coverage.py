from src.extraction.extractor import StructuredExtractor
from src.extraction.fields import CANONICAL_FIELDS


def test_all_canonical_fields_are_present_and_stable():
    record = StructuredExtractor().extract("Bid1", [{"record": {"source_file": "rfp.pdf", "page_number": 1, "source_locator": {}, "bid_id": "Bid1", "text": "JA-207652 title deadline submission bond delivery product specification"}}])
    assert list(record.fields) == list(CANONICAL_FIELDS)
    assert record.fields["Bid Number"].value is not None
