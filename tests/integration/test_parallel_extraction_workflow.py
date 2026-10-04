from threading import Barrier, BrokenBarrierError

from src.agents.graph import AnalysisWorkflow
from src.agents.retrieval_agent import RetrievalAgent
from src.agents.settings import Settings
from src.agents.state import ExtractionResult, ModelUsage, WorkflowState


class Search:
    def search(self, query, configuration="hybrid"):
        record = {
            "record_id": "r1",
            "source_file": "rfp.html",
            "page_number": 1,
            "bid_id": "Bid1",
            "source_locator": {},
            "text": "Submission deadline: 2026-12-01. Bid bond: 5% of bid price.",
        }
        result = {"record_id": "r1", "record": record, "authority_status": "current"}
        return {"results": [result], "diagnostics": [], "query_variants": {"variants": [query.text]}}


class PartiallyFailingProvider:
    def __init__(self):
        self.barrier = Barrier(2, timeout=0.5)

    def extract_fields(self, evidence, field_names):
        try:
            self.barrier.wait()
        except BrokenBarrierError:
            pass
        if "bid_bond" in field_names:
            raise RuntimeError("commercial extraction failed")
        return ExtractionResult(
            values={"submission_deadline": "2026-12-01"},
            usage=ModelUsage(),
        )


def test_workflow_keeps_successful_group_when_another_group_fails(tmp_path):
    settings = Settings(
        index_path=str(tmp_path / "index.json"),
        trace_path=str(tmp_path / "trace.json"),
        langsmith_api_key=None,
    )
    workflow = AnalysisWorkflow(
        RetrievalAgent(Search()),
        model_provider=PartiallyFailingProvider(),
        settings=settings,
    )

    result = workflow.invoke(
        WorkflowState(
            mode="extraction",
            goal="submission deadline and bid bond",
            bid_ids=["Bid1"],
        )
    )

    assert result.final_output["fields"]["submission_deadline"]["value"] == "2026-12-01"
    assert result.final_output["fields"]["submission_deadline"]["status"] == "supported"
    assert result.final_output["fields"]["bid_bond"]["status"] == "review_required"
    assert any(item.code == "extraction_group_failed" for item in result.diagnostics)