from src.extraction.extractor import StructuredExtractor
from src.extraction.identity import normalized_bid_id


def test_identity_uses_official_number_when_available():
    assert normalized_bid_id("Initial_docs/Bid1", "JA-207652") == "JA-207652"


def test_identity_normalizes_folder_when_number_missing():
    value = normalized_bid_id("C:/bids/New Bid 01")
    assert value.isdigit()
    assert len(value) == 12
    assert value == normalized_bid_id("C:/bids/New Bid 01")


def test_extractor_preserves_matching_indexed_bid_identity():
    evidence = [{"record": {
        "source_file": "rfp.pdf",
        "page_number": 1,
        "source_locator": {"page": 1},
        "bid_id": "Bid1",
        "text": "Submission deadline October 20, 2026.",
    }}]

    record = StructuredExtractor().extract("Bid1", evidence)

    assert record.bid_id == "Bid1"
    assert record.fields["Due Date"].citations[0].bid_id == record.bid_id


def test_extractor_discards_evidence_from_another_bid():
    evidence = [{"record": {
        "source_file": "other.pdf",
        "page_number": 1,
        "source_locator": {"page": 1},
        "bid_id": "OtherBid",
        "text": "Submission deadline October 20, 2026.",
    }}]

    record = StructuredExtractor().extract("Unseen Bid", evidence)

    assert record.bid_id.isdigit()
    assert len(record.bid_id) == 12
    assert record.fields["Due Date"].status == "not_found"
    assert record.fields["Due Date"].citations == []
