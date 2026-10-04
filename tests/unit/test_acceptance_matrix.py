from src.agents.state import AnalysisResponse


def test_response_schema_is_stable_for_both_modes():
    for output in ({"fields": {}}, {"answer": "Not found in documents", "citations": [], "evidence_by_bid": {}, "found": False}):
        response = AnalysisResponse(run_id="run", status="completed", output=output)
        assert {"run_id", "status", "output", "diagnostics", "trace_reference", "evaluation"} <= set(response.model_dump())
