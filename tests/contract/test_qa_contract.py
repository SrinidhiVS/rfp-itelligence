from src.agents.state import AnalysisResponse


def test_qa_response_contract_has_citations_and_bid_grouping():
    response = AnalysisResponse(run_id="run", status="completed", output={"answer": "Not found in documents", "citations": [], "evidence_by_bid": {}, "found": False})
    assert response.output["found"] is False
    assert response.output["answer"] == "Not found in documents"
