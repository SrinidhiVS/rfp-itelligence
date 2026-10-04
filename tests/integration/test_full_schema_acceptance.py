from src.extraction.extractor import StructuredExtractor
from src.extraction.fields import CANONICAL_FIELDS


def test_all_fixture_identities_have_complete_schema():
    for folder in ("Bid1", "Bid2", "Unseen Bid"):
        record = StructuredExtractor().extract(folder, [])
        assert list(record.fields) == list(CANONICAL_FIELDS)
        assert len(record.fields) == 20
