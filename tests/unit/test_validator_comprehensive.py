from src.agents.state import ExtractionField
from src.agents.validator_agent import validate_fields


def test_validator_rejects_unsupported_non_null_field_without_citation():
    field = ExtractionField.model_construct(name="deadline", value="guessed", status="rejected", citations=[], notes="unsupported claim")
    results, diagnostics = validate_fields({"deadline": field})
    assert results[0].status == "rejected"
    assert diagnostics[0].retryable is True
