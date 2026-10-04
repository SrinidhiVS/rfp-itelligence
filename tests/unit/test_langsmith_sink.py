from src.agents.langsmith_sink import LangSmithTraceSink


def test_langsmith_sink_falls_back_without_credentials():
    assert LangSmithTraceSink().record({"trace_id": "local", "events": []}) is None


def test_langsmith_sink_uploads_trace_events_and_reports_failures():
    class FakeClient:
        def __init__(self):
            self.create_args = None
            self.inputs = None
            self.outputs = None
            self.end_time = None

        def create_run(self, **kwargs):
            self.create_args = kwargs
            self.inputs = kwargs["inputs"]

        def update_run(self, run_id, *, outputs, end_time):
            self.run_id = run_id
            self.outputs = outputs
            self.end_time = end_time

    sink = LangSmithTraceSink()
    sink.client = FakeClient()
    trace = {
        "trace_id": "00000000-0000-4000-8000-000000000001",
        "run_id": "run-1",
        "events": [{"event_type": "tool_call", "tool_name": "retrieval"}],
    }

    result = sink.record(trace)

    assert result == trace["trace_id"]
    assert sink.client.create_args["id"] == trace["trace_id"]
    assert sink.client.run_id == trace["trace_id"]
    assert sink.client.end_time is not None
    assert sink.client.inputs["trace_id"] == trace["trace_id"]
    assert sink.client.outputs["events"] == trace["events"]


def test_langsmith_sink_does_not_raise_when_remote_client_fails():
    class FailingClient:
        def create_run(self, **kwargs):
            raise RuntimeError("remote unavailable")

    sink = LangSmithTraceSink()
    sink.client = FailingClient()
    assert sink.record({"trace_id": "local-1", "events": []}) is None
