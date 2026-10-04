from src.extraction.extractor import StructuredExtractor


def test_equal_addendum_order_with_conflicting_authority_requires_review():
    evidence = [
        {"record": {"source_file": "base.pdf", "page_number": 1, "source_locator": "deadline", "bid_id": "Bid1", "doc_type": "rfp", "text": "Submission deadline: October 10."}},
        {"record": {"source_file": "current.pdf", "page_number": 1, "source_locator": {}, "bid_id": "Bid1", "doc_type": "addendum", "addendum_number": 2, "document_date": "2026-10-01", "text": "submission deadline October 20"}, "authority_status": "current"},
        {"record": {"source_file": "old.pdf", "page_number": 1, "source_locator": {}, "bid_id": "Bid1", "doc_type": "addendum", "addendum_number": 2, "document_date": "2026-10-01", "text": "submission deadline October 25"}, "authority_status": "superseded"},
    ]
    record = StructuredExtractor().extract("Bid1", evidence)
    assert record.fields["Due Date"].status == "review_required"
    assert record.addendum_changes[0].review_required is True
    assert record.addendum_changes[0].previous_citations[0].file == "base.pdf"
    assert {citation.file for citation in record.addendum_changes[0].current_citations} == {"current.pdf", "old.pdf"}
