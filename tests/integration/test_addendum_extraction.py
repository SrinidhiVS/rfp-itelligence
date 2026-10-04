from src.extraction.extractor import StructuredExtractor


def test_addendum_change_retains_previous_and_current_values():
    evidence = [
        {"record": {"source_file": "base.pdf", "page_number": 1, "source_locator": {}, "bid_id": "Bid1", "doc_type": "rfp", "text": "submission deadline October 10"}},
        {"record": {"source_file": "addendum.pdf", "page_number": 1, "source_locator": {}, "bid_id": "Bid1", "doc_type": "addendum", "addendum_number": 1, "text": "submission deadline revised October 20"}},
    ]
    record = StructuredExtractor().extract("Bid1", evidence)
    change = record.addendum_changes[0]
    assert change.previous_value
    assert "October 20" in change.current_value
    assert change.controlling_citation.file == "addendum.pdf"


def test_addendum_updates_payment_terms_and_keeps_prior_and_revised_citations():
    evidence = [
        {"record": {"source_file": "base.pdf", "page_number": 1, "source_locator": "payment terms", "bid_id": "Bid1", "doc_type": "rfp", "text": "Payment terms: Net 30."}},
        {"record": {"source_file": "addendum-1.pdf", "page_number": 2, "source_locator": "revised terms", "bid_id": "Bid1", "doc_type": "addendum", "addendum_number": 1, "text": "Payment terms: Net 45."}},
    ]

    record = StructuredExtractor().extract("Bid1", evidence)

    change = next(change for change in record.addendum_changes if change.field == "Payment Terms")
    assert record.fields["Payment Terms"].value == "Net 45"
    assert change.previous_value == "Net 30"
    assert change.current_value == "Net 45"
    assert change.previous_citations[0].file == "base.pdf"
    assert change.current_citations[0].file == "addendum-1.pdf"
