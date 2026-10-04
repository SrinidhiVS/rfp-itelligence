from src.extraction.validation import review_required_field


def test_ambiguous_value_becomes_review_required_without_guessing():
    field = review_required_field("Model_no", "Conflicting model numbers require review.")
    assert field.value is None
    assert field.status == "review_required"
    assert field.confidence == 0.0
