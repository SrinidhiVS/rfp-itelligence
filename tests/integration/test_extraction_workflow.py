from pathlib import Path
from shutil import copyfile

from src.agents.graph import AnalysisWorkflow
from src.agents.retrieval_agent import RetrievalAgent
from src.agents.settings import Settings
from src.agents.state import WorkflowState
from src.search.storage import CorpusStore


class FakeSearch:
    def __init__(self, evidence):
        self.evidence = evidence

    def search(self, query, configuration="hybrid"):
        return {"results": self.evidence, "diagnostics": [], "query_variants": {"variants": [query.text]}}


def evidence(text, bid_id="Bid1"):
    return [{"record_id": "r1", "rank": 1, "score": 1.0, "retrieval_methods": ["keyword"], "source_completeness": "complete", "authority_status": "current", "superseded_by": None, "record": {"record_id": "r1", "source_file": "rfp.html", "page_number": 1, "bid_id": bid_id, "source_locator": {}, "text": text}}]


def test_extraction_workflow_returns_cited_fields():
    workflow = AnalysisWorkflow(RetrievalAgent(FakeSearch(evidence("Submission deadline: October 10, 2026"))))
    result = workflow.invoke(__import__("src.agents.state", fromlist=["WorkflowState"]).WorkflowState(mode="extraction", goal="extract", bid_ids=["Bid1"]))
    assert "fields" in result.final_output, (result.final_output, result.diagnostics)
    assert result.final_output["fields"]["submission_deadline"]["citations"]
    assert result.trace_reference
    assert {event["node"] for event in result.trace.events} >= {"Planner", "Ingestion", "Retrieval", "Extraction", "Reconciliation", "Validation", "Report"}


def test_unseen_staged_bid_is_indexed_and_cited_in_same_run(tmp_path, monkeypatch):
    root = tmp_path / "BidNew"
    root.mkdir()
    copyfile(Path("tests/fixtures/partial-bid/valid.html"), root / "valid.html")
    corpus_path = tmp_path / "corpus.json"
    monkeypatch.setenv("RFP_INDEX_PATH", str(corpus_path))
    monkeypatch.setenv("RFP_CHROMA_PATH", str(tmp_path / "chroma"))
    monkeypatch.setenv("RFP_SUBMISSION_ROOT", str(tmp_path))
    chroma_syncs = []
    monkeypatch.setattr(
        "src.agents.ingestion_agent.sync_chroma_index",
        lambda store: chroma_syncs.append([record.bid_id for record in store.load().records]) or {"failed": 0},
        raising=False,
    )
    settings = Settings(index_path=str(corpus_path), trace_path=str(tmp_path / "trace.json"))
    workflow = AnalysisWorkflow(RetrievalAgent(corpus_path=corpus_path), settings=settings)
    state = WorkflowState(mode="extraction", goal="submission deadline", bid_ids=["BidNew"], submitted_bid_folders={"BidNew": str(root)}, max_retries=0)
    result = workflow.invoke(state)
    assert result.status != "failed"
    assert any(record.bid_id == "BidNew" and "2026-12-01" in record.text for record in CorpusStore(corpus_path).load().records)
    assert chroma_syncs and "BidNew" in chroma_syncs[0]
    assert result.final_output["fields"]["submission_deadline"]["citations"], (result.diagnostics, result.retrieved_evidence)


def test_unchanged_and_changed_staged_files_preserve_other_bids(tmp_path, monkeypatch):
    corpus_path = tmp_path / "corpus.json"
    monkeypatch.setenv("RFP_INDEX_PATH", str(corpus_path))
    monkeypatch.setenv("RFP_CHROMA_PATH", str(tmp_path / "chroma"))
    monkeypatch.setenv("RFP_SUBMISSION_ROOT", str(tmp_path))
    for bid in ("BidA", "BidB"):
        folder = tmp_path / bid
        folder.mkdir()
        copyfile(Path("tests/fixtures/partial-bid/valid.html"), folder / "valid.html")
    workflow = AnalysisWorkflow(RetrievalAgent(corpus_path=corpus_path), settings=Settings(index_path=str(corpus_path), trace_path=str(tmp_path / "trace.json")))

    def analyze(bid):
        return workflow.invoke(WorkflowState(mode="extraction", goal="submission deadline", bid_ids=[bid], submitted_bid_folders={bid: str(tmp_path / bid)}, max_retries=0))

    analyze("BidA")
    analyze("BidB")
    before = CorpusStore(corpus_path).load().records
    bid_a_ids = {item.record_id for item in before if item.bid_id == "BidA"}
    bid_b_ids = {item.record_id for item in before if item.bid_id == "BidB"}
    analyze("BidA")
    repeated = CorpusStore(corpus_path).load().records
    assert {item.record_id for item in repeated if item.bid_id == "BidA"} == bid_a_ids
    assert {item.record_id for item in repeated if item.bid_id == "BidB"} == bid_b_ids
    (tmp_path / "BidA" / "valid.html").write_text("<html><body><p>Deadline: 2026-12-15</p></body></html>", encoding="utf-8")
    analyze("BidA")
    changed = CorpusStore(corpus_path).load().records
    assert any(item.bid_id == "BidA" and "2026-12-15" in item.text for item in changed)
    assert not any(item.bid_id == "BidA" and "2026-12-01" in item.text for item in changed)
    assert {item.record_id for item in changed if item.bid_id == "BidB"} == bid_b_ids


def test_partial_submission_reports_failed_file_but_retains_valid_evidence(tmp_path, monkeypatch):
    root = tmp_path / "BidPartial"
    root.mkdir()
    copyfile(Path("tests/fixtures/partial-bid/valid.html"), root / "valid.html")
    copyfile(Path("tests/fixtures/partial-bid/broken.pdf"), root / "broken.pdf")
    corpus_path = tmp_path / "corpus.json"
    monkeypatch.setenv("RFP_INDEX_PATH", str(corpus_path))
    monkeypatch.setenv("RFP_CHROMA_PATH", str(tmp_path / "chroma"))
    monkeypatch.setenv("RFP_SUBMISSION_ROOT", str(tmp_path))
    workflow = AnalysisWorkflow(RetrievalAgent(corpus_path=corpus_path), settings=Settings(index_path=str(corpus_path), trace_path=str(tmp_path / "trace.json")))
    result = workflow.invoke(WorkflowState(mode="extraction", goal="submission deadline", bid_ids=["BidPartial"], submitted_bid_folders={"BidPartial": str(root)}, max_retries=0))
    assert result.status == "partial"
    assert any("broken.pdf" in item.message for item in result.diagnostics)
    assert result.final_output["fields"]["submission_deadline"]["citations"]


def test_failed_changed_source_retains_previously_indexed_scope(tmp_path, monkeypatch):
    root = tmp_path / "BidPartial"
    root.mkdir()
    copyfile(Path("tests/fixtures/partial-bid/valid.html"), root / "valid.html")
    copyfile(Path("tests/fixtures/partial-bid/valid.html"), root / "previous.html")
    corpus_path = tmp_path / "corpus.json"
    monkeypatch.setenv("RFP_INDEX_PATH", str(corpus_path))
    monkeypatch.setenv("RFP_CHROMA_PATH", str(tmp_path / "chroma"))
    monkeypatch.setenv("RFP_SUBMISSION_ROOT", str(tmp_path))
    workflow = AnalysisWorkflow(RetrievalAgent(corpus_path=corpus_path), settings=Settings(index_path=str(corpus_path), trace_path=str(tmp_path / "trace.json")))
    state = WorkflowState(mode="extraction", goal="submission deadline", bid_ids=["BidPartial"], submitted_bid_folders={"BidPartial": str(root)}, max_retries=0)
    workflow.invoke(state)
    previous_ids = {item.record_id for item in CorpusStore(corpus_path).load().records if item.source_file == "previous.html"}
    assert previous_ids
    (root / "valid.html").write_text("<html><body><p>Deadline: 2026-12-15</p></body></html>", encoding="utf-8")
    copyfile(Path("tests/fixtures/partial-bid/broken.pdf"), root / "previous.html")
    result = workflow.invoke(state)
    current = CorpusStore(corpus_path).load().records
    assert result.status == "partial"
    assert {item.record_id for item in current if item.source_file == "previous.html"} == previous_ids
    assert any(item.source_file == "valid.html" and "2026-12-15" in item.text for item in current)


def test_requested_goal_limits_reported_fields_and_names_unsupported_work(tmp_path):
    workflow = AnalysisWorkflow(
        RetrievalAgent(FakeSearch(evidence("Submission deadline: October 10, 2026"))),
        settings=Settings(trace_path=str(tmp_path / "trace.json")),
    )
    deadline = workflow.invoke(WorkflowState(mode="extraction", goal="submission deadline", bid_ids=["Bid1"], max_retries=0))
    assert set(deadline.final_output["fields"]) == {"submission_deadline"}
    unknown = workflow.invoke(WorkflowState(mode="extraction", goal="calculate carbon emissions", bid_ids=["Bid1"], max_retries=0))
    assert unknown.final_output["fields"] == {}
    assert unknown.final_output["unsupported_work"]
    assert unknown.status == "partial"
