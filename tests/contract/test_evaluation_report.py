from src.agents.report_agent import build_evaluation
from src.agents.state import ExtractionField, WorkflowState


def test_evaluation_report_contains_citation_coverage_and_dispositions():
    state = WorkflowState(mode="extraction", goal="extract", draft_fields={"deadline": ExtractionField(name="deadline")})
    report = build_evaluation(state)
    assert report.citation_coverage == 1
    assert report.field_dispositions["deadline"] == "not_found"
