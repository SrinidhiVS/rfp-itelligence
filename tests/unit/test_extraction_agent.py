from src.agents.extraction_agent import extract_fields
from src.agents.extraction_agent import FIELD_TERMS
from src.field_registry import AGENT_FIELD_ALIASES


def evidence(text="Submission deadline: October 10, 2026"):
    return [{"record": {"source_file": "rfp.html", "page_number": 1, "bid_id": "Bid1", "source_locator": {}, "text": text}, "authority_status": "current"}]


def test_extraction_preserves_field_citation():
    result = extract_fields(evidence(), ["submission_deadline"])
    assert result["submission_deadline"].value
    assert result["submission_deadline"].citations[0].file == "rfp.html"


def test_missing_field_is_explicit_not_found():
    result = extract_fields(evidence(), ["warranty"])
    assert result["warranty"].value is None
    assert result["warranty"].notes == "Not found in documents"


def test_field_extraction_uses_relevant_value_and_preserves_units():
    items = evidence("Project meeting October 1, 2026. Submission deadline: October 10, 2026.") + evidence("Bid bond: 5% of bid price")
    results = extract_fields(items, ["submission_deadline", "bid_bond"])
    assert results["submission_deadline"].value == "October 10, 2026"
    assert results["bid_bond"].value == "5% of bid price"
    assert all(field.citations and field.status == "supported" for field in results.values())


def test_table_deadline_and_unsupported_model_value():
    table = evidence("Deadline\n2026-12-01")
    assert extract_fields(table, ["submission_deadline"])["submission_deadline"].value == "2026-12-01"
    unsupported = extract_fields(table, ["submission_deadline"], {"submission_deadline": "2030-01-01"})["submission_deadline"]
    assert unsupported.status != "supported"


def test_page_reference_is_not_a_deadline_date():
    field = extract_fields(evidence("Following the submission deadline, refer to page 7 for details."), ["submission_deadline"])["submission_deadline"]
    assert field.value is None and field.status != "supported"


def test_warranty_field_extracts_short_qualified_value():
    field = extract_fields(evidence("Device requirements\nWarranty: 3-year minimum\nOther conditions apply."), ["warranty"])["warranty"]
    assert field.value == "3-year minimum"
    assert field.citations[0].file == "rfp.html"


def test_model_number_field_extracts_source_product_identifier():
    field = extract_fields(evidence("SI# CC7802 Dell Latitude 5550"), ["model_number"])["model_number"]
    assert field.value == "Dell Latitude 5550"
    assert field.citations[0].file == "rfp.html"


def test_mandatory_requirement_extraction_uses_request_context():
    text = "Each JV partner must complete Sections A through D.\nOne (1) form must be provided for each subcontractor."
    field = extract_fields(evidence(text), ["mandatory_requirements"], goal="What requirement applies to forms for subcontractors?")["mandatory_requirements"]
    assert field.value == "One (1) form must be provided for each subcontractor."


def test_unrelated_requirement_passage_does_not_shadow_relevant_evidence():
    items = evidence("Warranty service must be performed within five days.") + evidence("One (1) form must be provided for each subcontractor.")
    field = extract_fields(items, ["mandatory_requirements"], goal="What requirement applies to forms for subcontractors?")["mandatory_requirements"]
    assert field.value == "One (1) form must be provided for each subcontractor."


def test_agent_field_terms_are_shared_with_the_field_registry():
    assert FIELD_TERMS == AGENT_FIELD_ALIASES
