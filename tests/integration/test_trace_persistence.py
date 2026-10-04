import json

from src.agents.tracing import TraceRecorder


def test_trace_can_be_persisted_as_safe_json(tmp_path):
    recorder = TraceRecorder("persisted")
    recorder.event("Report", "end", output_value={"status": "completed"})
    path = tmp_path / "trace.json"
    path.write_text(recorder.trace.model_dump_json(), encoding="utf-8")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["trace_id"] == "persisted"
    assert payload["events"][0]["node"] == "Report"
