from pathlib import Path

from src.agents.graph import AnalysisWorkflow
from src.agents.retrieval_agent import RetrievalAgent
from src.agents.settings import Settings
from src.agents.state import WorkflowState
from src.search.storage import CorpusStore
from tests.fixtures.robustness.unseen_bid_factory import create_unseen_bid_folder


def test_unseen_supported_bid_reaches_cited_qa_in_same_run(tmp_path, monkeypatch):
    descriptor, bid_folder = create_unseen_bid_folder(tmp_path / "submissions")
    corpus_path = tmp_path / "corpus.json"
    monkeypatch.setenv("RFP_INDEX_PATH", str(corpus_path))
    monkeypatch.setenv("RFP_CHROMA_PATH", str(tmp_path / "chroma"))
    monkeypatch.setenv("RFP_SUBMISSION_ROOT", str(tmp_path / "submissions"))
    monkeypatch.setattr(
        "src.agents.ingestion_agent.sync_chroma_index",
        lambda _store: {"failed": 0, "diagnostics": []},
    )

    settings = Settings(index_path=str(corpus_path), trace_path=str(tmp_path / "trace.json"), trace_enabled=False)
    workflow = AnalysisWorkflow(RetrievalAgent(corpus_path=corpus_path), settings=settings)
    result = workflow.invoke(
        WorkflowState(
            mode="qa",
            goal=descriptor["qa_question"],
            bid_ids=[descriptor["bid_id"]],
            submitted_bid_folders={descriptor["bid_id"]: str(bid_folder)},
            max_retries=0,
        )
    )

    records = CorpusStore(corpus_path).load().records
    assert result.status == "completed", (result.diagnostics, result.retrieved_evidence)
    assert any("local Chroma vector index is missing" in item.message for item in result.diagnostics)
    assert any(record.bid_id == descriptor["bid_id"] and descriptor["qa_expected_answer"] in record.text for record in records)
    assert result.final_output["found"] is True
    assert descriptor["qa_expected_answer"] in result.final_output["answer"]
    assert result.final_output["citations"]
    assert all(citation["bid_id"] == descriptor["bid_id"] for citation in result.final_output["citations"])
    assert any(
        citation["file"] == descriptor["qa_source_file"] and citation["page"] == 1
        for citation in result.final_output["citations"]
    )
