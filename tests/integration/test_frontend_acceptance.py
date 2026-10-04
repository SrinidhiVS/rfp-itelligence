from src.extraction.fields import CANONICAL_FIELDS
from src.frontend.state import ExtractionRequest, QuestionRequest
from src.frontend.views import answer_view, extraction_view


def test_frontend_acceptance_envelope_for_q_and_extraction():
    answer = answer_view({"run_id": "q", "status": "completed", "output": {"answer": "Not found in documents", "found": False, "citations": [], "evidence_by_bid": {}}, "diagnostics": [], "trace_reference": "q", "evaluation": {}})
    extraction = extraction_view({"run_id": "e", "status": "completed", "output": {"fields": {}, "addendum_changes": [], "validation": []}, "diagnostics": [], "trace_reference": "e", "evaluation": {}})
    assert answer["answer"] == "Not found in documents"
    assert list(extraction["fields"]) == list(CANONICAL_FIELDS)
    assert all(field["status"] == "unavailable" for field in extraction["fields"].values())
    assert extraction["validation_counts"] is None
    assert QuestionRequest(question="q", bid_ids=["Bid1"]).mode == "qa"
    assert ExtractionRequest(bid_id="Bid1").mode == "extraction"
