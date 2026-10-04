from src.agents.state import ModelUsage
from src.agents.tracing import TraceRecorder


def test_local_trace_remains_available_without_provider():
    recorder = TraceRecorder("offline")
    recorder.event("Report", "end", status="ok")
    assert recorder.trace.trace_id == "offline"
    assert recorder.trace.events[0]["status"] == "ok"


def test_model_call_trace_preserves_reported_and_unavailable_usage():
    recorder = TraceRecorder("model-usage", run_id="run-usage")
    recorder.model_call(
        "Extraction",
        ModelUsage(input_tokens=4, output_tokens=2, total_tokens=6, availability="reported"),
        duration_ms=1.0,
    )
    recorder.model_call("Extraction", ModelUsage(), duration_ms=0.5)

    reported, unavailable = recorder.trace.events
    assert reported["usage"]["total_tokens"] == 6
    assert reported["usage"]["availability"] == "reported"
    assert unavailable["usage"]["availability"] == "unavailable"
    assert unavailable["usage"]["total_tokens"] is None
