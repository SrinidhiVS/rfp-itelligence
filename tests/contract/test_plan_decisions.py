from src.agents.messages import make_message, validate_message
from src.agents.providers import DeterministicModelProvider
from src.agents.tracing import TraceRecorder, safe_summary


def test_plan_decisions_are_executable_contracts():
    message = make_message("run", "retrieval", "Retrieval", "evidence", {"results": []}, recipient="Extraction")
    assert validate_message(message).payload_type == "evidence"
    assert DeterministicModelProvider().extract_fields([], []).values == {}
    assert "text" not in safe_summary({"text": "source", "record_id": "r"})
    recorder = TraceRecorder("trace")
    recorder.event("Retrieval", "tool_call", output_value={"result_count": 0})
    assert recorder.trace.events[0]["event"] == "tool_call"
