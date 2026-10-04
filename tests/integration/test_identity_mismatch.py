from src.extraction.extractor import StructuredExtractor


def test_wrong_bid_evidence_does_not_populate_requested_folder():
    evidence = [{"record": {"source_file": "other.pdf", "page_number": 1, "source_locator": {}, "bid_id": "OtherBid", "text": "submission deadline October 20"}}]
    record = StructuredExtractor().extract("Unseen Bid", evidence)
    assert record.bid_id.isdigit()
    assert len(record.bid_id) == 12
    assert record.fields["Due Date"].status == "not_found"
    assert record.fields["Due Date"].citations == []
