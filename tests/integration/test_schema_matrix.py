from src.extraction.extractor import StructuredExtractor
from src.extraction.fields import CANONICAL_FIELDS


def test_schema_matrix_is_stable_across_bid_ids():
    records = [StructuredExtractor().extract(bid, []) for bid in ("Bid1", "Bid2", "Unseen Bid")]
    assert all(tuple(record.fields) == CANONICAL_FIELDS for record in records)
