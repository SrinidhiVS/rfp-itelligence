from fastapi.testclient import TestClient
from src.api import app as app_module


def test_extract_validation_error_has_structured_detail():
    response = TestClient(app_module.app).post("/v1/analysis/extract", json={"mode": "qa", "bid_id": "Bid1"})
    assert response.status_code == 422
    assert "detail" in response.json()


def test_qa_validation_error_has_structured_detail():
    response = TestClient(app_module.app).post("/v1/analysis/qa", json={"mode": "qa", "question": "", "bid_ids": []})
    assert response.status_code == 422
    assert "detail" in response.json()
