from src.agents.report_agent import citation_coverage
from src.agents.state import ExtractionField


def test_citation_threshold_is_executable():
    fields = {f"field-{i}": ExtractionField(name=f"field-{i}") for i in range(20)}
    assert citation_coverage(fields) >= 0.95


def test_unsupported_values_are_not_counted_as_supported():
    fields = {"missing": ExtractionField(name="missing")}
    assert citation_coverage(fields) == 1.0
