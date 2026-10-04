from src.extraction.extractor import StructuredExtractor
from src.extraction.validation import review_required_field
from src.extraction.record_builder import build_record


def test_review_required_is_counted_separately():
    record = build_record("bid", {"field": review_required_field("field", "ambiguous")})
    assert record.validation.review_required == 1


def test_missing_record_has_explicit_not_found_diagnostic():
    record = StructuredExtractor().extract("bid", [])
    assert record.diagnostics[0].code == "empty_evidence"
    assert record.validation.not_found == 20
