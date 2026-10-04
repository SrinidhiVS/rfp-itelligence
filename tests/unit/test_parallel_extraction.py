from threading import Barrier, BrokenBarrierError, Event, Lock
import time

from src.agents.graph import AnalysisWorkflow
from src.agents.state import ExtractionResult, ModelUsage
from src.agents.tracing import TraceRecorder


def evidence():
    record = {
        "record_id": "r1",
        "source_file": "rfp.html",
        "page_number": 1,
        "bid_id": "Bid1",
        "source_locator": {},
        "text": "Submission deadline: 2026-12-01. Bid bond: 5% of bid price.",
    }
    return [{"record": record, "authority_status": "current"}]


class BarrierProvider:
    def __init__(self, expected_calls=2):
        self.barrier = Barrier(expected_calls, timeout=0.5)
        self.calls = []
        self.active = 0
        self.max_active = 0
        self.lock = Lock()

    def extract_fields(self, evidence_items, field_names):
        with self.lock:
            self.calls.append(tuple(field_names))
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            self.barrier.wait()
        except BrokenBarrierError:
            pass
        finally:
            with self.lock:
                self.active -= 1
        values = {
            "submission_deadline": "2026-12-01",
            "bid_bond": "5% of bid price",
        }
        return ExtractionResult(
            values={field: values[field] for field in field_names},
            usage=ModelUsage(),
        )


def test_extraction_runs_planner_groups_concurrently_and_honors_retry_fields():
    provider = BarrierProvider()
    workflow = object.__new__(AnalysisWorkflow)
    workflow.model_provider = provider
    data = {
        "_trace": TraceRecorder("unit"),
        "mode": "extraction",
        "goal": "submission deadline and bid bond",
        "plan": {
            "field_groups": {
                "submission": ["submission_deadline"],
                "commercial": ["bid_bond"],
            }
        },
        "retry_fields": [],
        "retrieved_evidence": evidence(),
        "draft_fields": {},
        "diagnostics": [],
    }

    workflow._extraction(data)

    assert set(provider.calls) == {("submission_deadline",), ("bid_bond",)}
    assert set(data["draft_fields"]) == {"submission_deadline", "bid_bond"}

    retry_provider = BarrierProvider()
    workflow.model_provider = retry_provider
    retry_data = {**data, "_trace": TraceRecorder("retry"), "draft_fields": {}, "retry_fields": ["bid_bond"]}
    workflow._extraction(retry_data)
    assert retry_provider.calls == [("bid_bond",)]


def test_four_groups_overlap_without_exceeding_worker_limit_and_merge_in_plan_order():
    provider = BarrierProvider(expected_calls=4)
    workflow = object.__new__(AnalysisWorkflow)
    workflow.model_provider = provider
    groups = {
        "submission": ["submission_deadline"],
        "commercial": ["bid_bond"],
        "compliance": ["affidavits"],
        "product": ["model_number"],
    }
    data = {
        "_trace": TraceRecorder("four-groups"),
        "mode": "extraction",
        "goal": "extract complete bid record",
        "plan": {"field_groups": groups},
        "retry_fields": [],
        "retrieved_evidence": evidence(),
        "draft_fields": {},
        "diagnostics": [],
    }

    workflow._extraction(data)

    assert provider.max_active == 4
    assert list(data["draft_fields"]) == [field for fields in groups.values() for field in fields]


def test_dependent_group_waits_for_successful_prerequisite():
    prerequisite_finished = Event()
    dependent_started_early = []

    class DependentProvider:
        def extract_fields(self, evidence_items, field_names):
            if "submission_deadline" in field_names:
                time.sleep(0.03)
                prerequisite_finished.set()
            elif "bid_bond" in field_names and not prerequisite_finished.is_set():
                dependent_started_early.append(True)
            return ExtractionResult(values={}, usage=ModelUsage())

    workflow = object.__new__(AnalysisWorkflow)
    workflow.model_provider = DependentProvider()
    data = {
        "_trace": TraceRecorder("dependent-groups"),
        "mode": "extraction",
        "goal": "submission deadline and bid bond",
        "plan": {
            "field_groups": {
                "submission": ["submission_deadline"],
                "commercial": ["bid_bond"],
            },
            "group_dependencies": {"commercial": ["submission"]},
        },
        "retry_fields": [],
        "retrieved_evidence": evidence(),
        "draft_fields": {},
        "diagnostics": [],
    }

    workflow._extraction(data)

    assert prerequisite_finished.is_set()
    assert dependent_started_early == []