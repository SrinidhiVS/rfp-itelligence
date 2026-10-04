from fastapi.testclient import TestClient
from types import SimpleNamespace

from src.api import app as app_module
from src.extraction.fields import CANONICAL_FIELDS


def test_health_endpoint():
    response = TestClient(app_module.app).get("/health")
    assert response.status_code == 200


def test_root_endpoint_lists_api_routes():
    response = TestClient(app_module.app).get("/")
    assert response.status_code == 200
    assert "/v1/analysis/extract" in response.json()["endpoints"]


def test_qa_endpoint_not_found_is_structured(monkeypatch):
    class EmptyWorkflow:
        def invoke(self, state):
            state.status = "completed"
            state.final_output = {"answer": "Not found in documents", "citations": [], "evidence_by_bid": {}, "found": False}
            return state

    monkeypatch.setattr(app_module, "workflow", EmptyWorkflow())
    response = TestClient(app_module.app).post("/v1/analysis/qa", json={"mode": "qa", "question": "unknown", "bid_ids": ["Bid1"]})
    assert response.status_code == 200
    assert response.json()["output"]["answer"] == "Not found in documents"


def test_extraction_api_preserves_response_envelope_with_collection_values(monkeypatch):
    class ExtractionWorkflow:
        def invoke(self, state):
            state.status = "completed"
            state.retrieved_evidence = [{
                "record": {
                    "record_id": "product-1",
                    "source_file": "products.pdf",
                    "page_number": 1,
                    "source_locator": {"row": 1},
                    "bid_id": "Bid1",
                    "doc_type": "rfp",
                    "text": "Product: Laptop Alpha; quantity: 10; model number: ZX100.",
                }
            }]
            return state

    monkeypatch.setattr(app_module, "workflow", ExtractionWorkflow())

    response = TestClient(app_module.app).post(
        "/v1/analysis/extract",
        json={"mode": "extraction", "bid_id": "Bid1", "trace": False},
    )

    assert response.status_code == 200
    payload = response.json()
    assert {"run_id", "status", "output", "diagnostics", "trace_reference", "evaluation"} <= set(payload)
    assert set(CANONICAL_FIELDS) <= set(payload["output"]["fields"])
    product = payload["output"]["fields"]["Product"]
    assert isinstance(product["value"], list)
    assert product["value"][0]["value"] == "Laptop Alpha"
    assert product["value"][0]["citations"][0]["file"] == "products.pdf"
