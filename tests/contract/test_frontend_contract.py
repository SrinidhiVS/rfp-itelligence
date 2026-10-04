from src.frontend.state import ExtractionRequest, QuestionRequest


def test_question_request_matches_existing_contract():
    payload = QuestionRequest(question="deadline", bid_ids=["Bid1"]).model_dump(mode="json")
    assert payload == {"mode": "qa", "question": "deadline", "bid_ids": ["Bid1"], "trace": True}


def test_extraction_request_matches_existing_contract():
    payload = ExtractionRequest(bid_id="Bid1").model_dump(mode="json")
    assert payload == {"mode": "extraction", "bid_id": "Bid1", "max_retries": 2, "trace": True}
