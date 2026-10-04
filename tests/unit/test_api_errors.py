from fastapi.testclient import TestClient
from src.api import app as app_module


def test_api_rejects_wrong_mode():
    response = TestClient(app_module.app).post("/v1/analysis/extract", json={"mode": "qa", "bid_id": "Bid1"})
    assert response.status_code == 422
