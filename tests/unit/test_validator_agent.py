from src.agents.state import ExtractionField
from src.agents.validator_agent import validate_fields


def test_validator_accepts_cited_supported_field():
    results, diagnostics = validate_fields({"submission_deadline": ExtractionField(name="submission_deadline", value="2026-10-10", status="supported", citations=[{"file": "x", "bid_id": "Bid1"}])})
    assert results[0].status == "passed"
    assert diagnostics == []


def test_validator_rejects_invalid_dates_and_unsupported_values():
    fields = {"submission_deadline": ExtractionField(name="submission_deadline", value="2026-02-30", status="supported", citations=[{"file": "x", "bid_id": "Bid1"}]),
              "bid_bond": ExtractionField(name="bid_bond", value="-5%", status="supported", citations=[{"file": "x", "bid_id": "Bid1"}])}
    results, diagnostics = validate_fields(fields)
    assert all(item.status == "rejected" and not item.format_valid and item.retry_eligible for item in results)
    assert {item.field for item in diagnostics} == set(fields)


def test_validator_checks_value_against_exact_cited_evidence():
    field = ExtractionField(name="submission_deadline", value="2026-12-01", status="supported", citations=[{"file": "rfp.pdf", "page": 2, "bid_id": "Bid1"}])
    evidence = [{"record": {"source_file": "rfp.pdf", "page_number": 2, "bid_id": "Bid1", "text": "Submission deadline: 2026-12-15"}}]
    results, _ = validate_fields({"submission_deadline": field}, evidence)
    assert results[0].status == "rejected" and not results[0].evidence_supported


def test_validator_flags_bond_conflicting_with_mandatory_requirements():
    fields = {"bid_bond": ExtractionField(name="bid_bond", value="5%", status="supported", citations=[{"file": "rfp.pdf", "bid_id": "Bid1"}]),
              "mandatory_requirements": ExtractionField(name="mandatory_requirements", value="No bond required", status="supported", citations=[{"file": "rfp.pdf", "bid_id": "Bid1"}])}
    results, _ = validate_fields(fields)
    assert results[0].status == "rejected" and not results[0].consistency_valid
