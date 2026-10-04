from src.extraction.models import ExtractedField


def test_zero_and_false_are_supported_values():
    zero = ExtractedField(name="quantity", value=0, confidence=0.8, status="supported", citations=[{"file": "table.pdf", "bid_id": "bid"}])
    false = ExtractedField(name="Installation", value=False, confidence=0.8, status="supported", citations=[{"file": "rfp.pdf", "bid_id": "bid"}])
    assert zero.value == 0
    assert false.value is False
