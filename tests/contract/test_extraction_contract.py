from src.agents.state import AnalysisResponse, ExtractionField


def test_extraction_contract_supports_cited_and_unavailable_fields():
    supported = ExtractionField(name="deadline", value="date", status="supported", citations=[{"file": "rfp.html", "bid_id": "Bid1"}])
    unavailable = ExtractionField(name="bond", status="not_found", notes="Not found in documents")
    response = AnalysisResponse(run_id="run", status="completed", output={"fields": {"deadline": supported.model_dump(), "bond": unavailable.model_dump()}})
    assert response.output["fields"]["deadline"]["citations"]
    assert response.output["fields"]["bond"]["notes"] == "Not found in documents"
