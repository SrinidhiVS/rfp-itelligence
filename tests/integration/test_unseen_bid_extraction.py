from src.extraction.extractor import StructuredExtractor
from fastapi.testclient import TestClient
from src.agents.graph import AnalysisWorkflow
from src.agents.retrieval_agent import RetrievalAgent
from src.agents.settings import Settings
from src.api import app as app_module
from tests.fixtures.robustness.unseen_bid_factory import create_unseen_bid_folder


def test_unseen_bid_uses_same_schema_without_bid_specific_logic():
    record = StructuredExtractor().extract("Unseen District Bid", [])
    assert record.bid_id.isdigit()
    assert len(record.bid_id) == 12
    assert len(record.fields) == 20
    assert all(field.confidence == 0.0 for field in record.fields.values())
    assert f"generated numeric bid_id '{record.bid_id}'" in record.fields["Bid Number"].notes


def test_unseen_supported_bid_extracts_canonical_values_with_source_citations(tmp_path, monkeypatch):
    descriptor, _bid_folder = create_unseen_bid_folder(tmp_path / "submissions")
    corpus_path = tmp_path / "corpus.json"
    bid_id = descriptor["bid_id"]
    monkeypatch.setenv("RFP_INDEX_PATH", str(corpus_path))
    monkeypatch.setenv("RFP_CHROMA_PATH", str(tmp_path / "chroma"))
    monkeypatch.setenv("RFP_SUBMISSION_ROOT", str(tmp_path / "submissions"))
    monkeypatch.setattr(
        "src.agents.ingestion_agent.sync_chroma_index",
        lambda _store: {"failed": 0, "diagnostics": []},
    )

    settings = Settings(index_path=str(corpus_path), trace_path=str(tmp_path / "trace.json"), trace_enabled=False)
    workflow = AnalysisWorkflow(RetrievalAgent(corpus_path=corpus_path), settings=settings)
    monkeypatch.setattr(app_module, "workflow", workflow)
    response = TestClient(app_module.app).post(
        "/v1/analysis/extract",
        json={
            "mode": "extraction",
            "bid_id": bid_id,
            "submitted_bid_folders": {bid_id: bid_id},
            "max_retries": 0,
            "trace": False,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    fields = payload["output"]["fields"]
    for field_name, expected_value in descriptor["extraction_expected"].items():
        field = fields[field_name]
        assert expected_value in str(field["value"]), (field_name, field, payload["diagnostics"])
        assert field["citations"]
        assert all(citation["bid_id"] == bid_id for citation in field["citations"])
        assert any(
            citation["file"] == descriptor["extraction_source_files"][field_name]
            for citation in field["citations"]
        )
    assert fields["Due Date"]["citations"][0]["page"] == 1
