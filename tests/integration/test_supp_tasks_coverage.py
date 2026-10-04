import json
from pathlib import Path

from src.agents.graph import AnalysisWorkflow
from src.agents.retrieval_agent import RetrievalAgent
from src.agents.settings import Settings
from src.agents.state import WorkflowState
from tests.fixtures.supp_tasks_corpus import build_supp_tasks_corpus


FIXTURE = json.loads(Path("tests/fixtures/supp_tasks_coverage.json").read_text(encoding="utf-8"))


class FixtureSearch:
    def __init__(self, evidence_by_key, records):
        self.evidence_by_key = evidence_by_key
        self.records = records
        self.empty = False
        self.top_ks = []

    def search(self, query, configuration="hybrid"):
        self.top_ks.append(query.top_k)
        if self.empty:
            return {"results": [], "diagnostics": ["no_supporting_evidence"], "query_variants": {"variants": [query.text]}}
        text = query.text.casefold()
        bid_ids = query.filters.get("bid_id", [])
        if "addendum" in text:
            case = "addendum_change"
        elif "deadline" in text or "due date" in text:
            case = "latest_deadline"
        elif "affidavit" in text:
            case = "affidavit_requirements"
        elif "warranty" in text or "warranties" in text:
            case = "warranty_comparison"
        elif "bond" in text or "bid security" in text:
            case = "bond_not_established"
        else:
            case = None
        ids = FIXTURE["cases"].get(case, []) if case else []
        results = [
            self.evidence_by_key[key]
            for key in ids
            if self.evidence_by_key[key]["record"]["bid_id"] in bid_ids
        ]
        return {
            "results": results,
            "diagnostics": [] if results else ["no_supporting_evidence"],
            "query_variants": {"variants": [query.text]},
        }


def _workflow(tmp_path, evidence_by_key, records):
    settings = Settings(trace_enabled=False, trace_path=str(tmp_path / "trace.json"))
    return AnalysisWorkflow(RetrievalAgent(FixtureSearch(evidence_by_key, records)), settings=settings)


def test_all_five_representative_questions_and_missing_evidence_cases(tmp_path):
    evidence_by_key, indexed_records = build_supp_tasks_corpus(tmp_path / "search-index.json")
    workflow = _workflow(tmp_path, evidence_by_key, indexed_records)
    scenarios = [
        {
            "question": "What changed in Addendum 2?",
            "bid_ids": ["Bid1"],
            "expected": ("27-JUN-2024", "July 9, 2024"),
        },
        {
            "question": "What is the latest submission deadline?",
            "bid_ids": ["Bid1"],
            "expected": ("July 9, 2024",),
        },
        {
            "question": "What affidavit requirements apply to this bid?",
            "bid_ids": ["Bid2"],
            "expected": ("Mercury Affidavit", "$500 or more", "Warranty certificate or Affidavit to be presented upon award"),
            "expected_files": {"PORFP_-_Dell_Laptop_Final.pdf", "Mercury_Affidavit.pdf", "Contract_Affidavit.pdf"},
        },
        {
            "question": "Compare the warranty requirements for Bid1 and Bid2.",
            "bid_ids": ["Bid1", "Bid2"],
            "expected": ("Bid1", "Bid2", "Differences", "within five (5) business days", "Warranty certificate or Affidavit to be presented upon award"),
        },
        {
            "question": "Is a bond required, and what is the amount?",
            "bid_ids": ["Bid1"],
            "expected": ("do not establish",),
            "expected_found": False,
        },
    ]

    for scenario in scenarios:
        result = workflow.invoke(WorkflowState(mode="qa", goal=scenario["question"], bid_ids=scenario["bid_ids"]))
        output = result.final_output
        expected_status = "completed" if scenario.get("expected_found", True) else "partial"
        assert result.status == expected_status, (scenario["question"], result.final_output, result.diagnostics)
        assert output["found"] is scenario.get("expected_found", True)
        for expected_text in scenario["expected"]:
            assert expected_text.casefold() in output["answer"].casefold()
        if output["found"]:
            assert output["citations"]
        else:
            assert output["citations"] == []
        if "expected_files" in scenario:
            assert {citation["file"] for citation in output["citations"]} == scenario["expected_files"]
        requested_bids = set(scenario["bid_ids"])
        assert all(citation["bid_id"] in requested_bids for citation in output["citations"])
        assert all(
            citation["bid_id"] == claim["bid_id"]
            for claim in output["claims"]
            for citation in claim["citations"]
        )
        if "affidavit" in scenario["question"].casefold():
            expected_scope_count = sum(record["bid_id"] in scenario["bid_ids"] for record in indexed_records)
            assert workflow.retrieval.search_service.top_ks[-1] == expected_scope_count

    questions = FIXTURE["missing_evidence_questions"]
    for case in questions:
        workflow.retrieval.search_service.empty = True
        output = workflow.invoke(
            WorkflowState(
                mode="qa",
                goal=case["question"],
                bid_ids=case["bid_ids"],
            )
        ).final_output
        assert output["found"] is False
        assert output["claims"] == []
        assert output["citations"] == []
        assert "not establish" in output["answer"].casefold() or "not found" in output["answer"].casefold()