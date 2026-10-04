import json
from pathlib import Path


def test_example_trace_contains_all_workflow_stages():
    trace = json.loads(Path("traces/example-extraction.json").read_text(encoding="utf-8"))
    nodes = {event["node"] for event in trace["events"]}
    assert nodes == {"Planner", "Ingestion", "Retrieval", "Extraction", "Reconciliation", "Validation", "Report"}
    assert all("status" in event and "latency_ms" in event for event in trace["events"])
