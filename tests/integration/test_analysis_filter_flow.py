from fastapi.testclient import TestClient

from src.agents.graph import AnalysisWorkflow
from src.agents.retrieval_agent import RetrievalAgent
from src.agents.settings import Settings
from src.api import app as app_module
from src.search.index import IndexService
from src.search.search import SearchService
from src.search.storage import CorpusStore


def _chunk(record_id, bid_id, relative_path, doc_type, addendum_number, text):
    return {
        "chunk_id": record_id,
        "source_file": relative_path.rsplit("/", 1)[-1],
        "page_number": 1,
        "section_title": "Submission",
        "doc_type": doc_type,
        "addendum_number": addendum_number,
        "source_locator": {"relative_path": relative_path, "page_number": 1},
        "text": text,
    }


def _workflow(tmp_path):
    corpus_path = tmp_path / "corpus.json"
    store = CorpusStore(corpus_path)
    sources = {
        "Bid1": [
            _chunk("bid1-base", "Bid1", "rfp/base.pdf", "rfp", None, "Submission deadline: November 1, 2026. Contract term: three years."),
            _chunk("bid1-addendum1", "Bid1", "addenda/addendum-1.pdf", "addendum", 1, "Submission deadline: November 5, 2026."),
            _chunk("bid1-addendum2", "Bid1", "addenda/addendum-2.pdf", "addendum", 2, "Submission deadline: November 10, 2026."),
        ],
        "Bid2": [
            _chunk("bid2-addendum2", "Bid2", "addenda/addendum-2.pdf", "addendum", 2, "Submission deadline: November 12, 2026."),
        ],
        "Bid3": [
            _chunk("bid3-addendum2", "Bid3", "addenda/addendum-2.pdf", "addendum", 2, "Submission deadline: November 15, 2026."),
        ],
    }
    index = IndexService(store)
    for bid_id, chunks in sources.items():
        index.update({
            "bid_id": bid_id,
            "source_manifest": [{"relative_path": item["source_locator"]["relative_path"]} for item in chunks],
            "chunks": chunks,
        })
    workflow = AnalysisWorkflow(
        RetrievalAgent(SearchService(store.load().records)),
        settings=Settings(index_path=str(corpus_path), trace_path=str(tmp_path / "trace.json"), trace_enabled=False),
    )
    return workflow


def test_filters_flow_through_qa_extraction_and_multi_bid_citations(tmp_path, monkeypatch):
    workflow = _workflow(tmp_path)
    monkeypatch.setattr(app_module, "workflow", workflow)
    client = TestClient(app_module.app)
    filters = {"doc_type": "addendum", "addendum_number": 2}

    comparison = client.post(
        "/v1/analysis/qa",
        json={
            "mode": "qa",
            "question": "Compare the submission deadlines for Bid1 and Bid2.",
            "bid_ids": ["Bid1", "Bid2"],
            "filters": filters,
            "trace": False,
        },
    )
    assert comparison.status_code == 200, comparison.text
    qa_output = comparison.json()["output"]
    assert qa_output["found"] is True
    assert {claim["bid_id"] for claim in qa_output["claims"]} == {"Bid1", "Bid2"}
    assert all(citation["bid_id"] in {"Bid1", "Bid2"} for citation in qa_output["citations"])
    assert {citation["file"] for citation in qa_output["citations"]} == {"addendum-2.pdf"}
    assert "November 10, 2026" in qa_output["answer"]
    assert "November 12, 2026" in qa_output["answer"]
    assert "November 15, 2026" not in qa_output["answer"]

    extraction = client.post(
        "/v1/analysis/extract",
        json={
            "mode": "extraction",
            "bid_id": "Bid1",
            "filters": filters,
            "max_retries": 0,
            "trace": False,
        },
    )
    assert extraction.status_code == 200, extraction.text
    due_date = extraction.json()["output"]["fields"]["Due Date"]
    assert "2026-11-10" in str(due_date["value"])
    assert due_date["citations"]
    assert {citation["file"] for citation in due_date["citations"]} == {"addendum-2.pdf"}
    assert all(citation["bid_id"] == "Bid1" for citation in due_date["citations"])

    unfiltered = client.post(
        "/v1/analysis/qa",
        json={"mode": "qa", "question": "What changed in Addendum 2?", "bid_ids": ["Bid1"], "trace": False},
    )
    assert unfiltered.status_code == 200, unfiltered.text
    assert set(unfiltered.json()) == {"run_id", "status", "output", "diagnostics", "trace_reference", "evaluation"}
    assert isinstance(unfiltered.json()["output"]["answer"], str)
