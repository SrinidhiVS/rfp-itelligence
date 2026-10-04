from src.agents.state import ModelUsage
from src.agents.tracing import TraceRecorder, safe_summary


def test_trace_redacts_secrets_and_source_content():
    assert "secret-value" not in safe_summary("api_key=secret-value")
    assert "content" not in safe_summary({"content": "whole source document", "node": "Retrieval"})


def test_trace_records_latency_and_unavailable_tokens():
    recorder = TraceRecorder("trace-1")
    recorder.run("Planner", {"goal": "deadline"}, lambda: {"ok": True})
    event = recorder.trace.events[-1]
    assert event["latency_ms"] is not None
    assert event["token_usage"] == "unavailable"


def test_trace_records_distinct_model_usage_and_tool_calls():
    recorder = TraceRecorder("trace-1", run_id="run-1")
    recorder.model_call(
        "Extraction",
        ModelUsage(
            provider="openai",
            model="test-model",
            input_tokens=12,
            output_tokens=6,
            total_tokens=18,
            availability="reported",
        ),
        duration_ms=4.5,
    )
    recorder.tool_call(
        "retrieval",
        input_value={"query": "api_key=secret-value", "text": "source passage"},
        output_value={"result_count": 1},
        duration_ms=3.0,
    )

    model_event, tool_event = recorder.trace.events
    assert model_event["event_type"] == "model_call"
    assert model_event["usage"] == {
        "provider": "openai",
        "model": "test-model",
        "input_tokens": 12,
        "output_tokens": 6,
        "total_tokens": 18,
        "availability": "reported",
    }
    assert tool_event["event_type"] == "tool_call"
    assert tool_event["tool_name"] == "retrieval"
    assert tool_event["duration_ms"] == 3.0
    assert "secret-value" not in str(tool_event)
    assert "source passage" not in str(tool_event)


def test_trace_marks_missing_usage_unavailable():
    recorder = TraceRecorder("trace-2", run_id="run-2")
    recorder.model_call("Extraction", ModelUsage(), duration_ms=0)
    assert recorder.trace.events[0]["usage"]["availability"] == "unavailable"
    assert recorder.trace.events[0]["usage"]["input_tokens"] is None


def test_failed_tool_call_records_status_without_raw_exception():
    recorder = TraceRecorder("trace-3", run_id="run-3")

    def fail():
        raise RuntimeError("api_key=secret-value")

    try:
        recorder.run_tool("retrieval", {"query": "deadline"}, fail)
    except RuntimeError:
        pass
    else:
        raise AssertionError("tool failure was swallowed")

    event = recorder.trace.events[0]
    assert event["event_type"] == "tool_call"
    assert event["status"] == "failed"
    assert event["error_summary"] == "RuntimeError"
    assert "secret-value" not in str(event)
