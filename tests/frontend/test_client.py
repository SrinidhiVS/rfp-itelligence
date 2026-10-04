import httpx
import pytest

from src.frontend.client import FrontendClient, FrontendRequestError
from src.frontend.config import FrontendConfig
from src.frontend.state import ExtractionRequest, QuestionRequest


def test_client_maps_connection_failure():
    transport = httpx.Client(transport=httpx.MockTransport(lambda request: (_ for _ in ()).throw(httpx.ConnectError("offline"))))
    client = FrontendClient(FrontendConfig(), transport=transport)
    with pytest.raises(FrontendRequestError) as error:
        client.ask(QuestionRequest(question="deadline", bid_ids=["Bid1"]))
    assert error.value.error.category == "connection"


def test_client_rejects_malformed_response():
    transport = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"output": {}})))
    client = FrontendClient(FrontendConfig(), transport=transport)
    with pytest.raises(FrontendRequestError) as error:
        client.ask(QuestionRequest(question="deadline", bid_ids=["Bid1"]))
    assert error.value.error.category == "malformed_response"


def test_import_requires_folder_name_and_files():
    client = FrontendClient(FrontendConfig(), transport=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}))))
    with pytest.raises(FrontendRequestError) as error:
        client.import_bid_files("", [])
    assert error.value.error.category == "validation"


def test_import_bid_files_syncs_updated_corpus_to_chroma(tmp_path, monkeypatch):
    import src.frontend.client as client_module

    calls = {}
    upload = type("Upload", (), {"name": "rfp.html", "getvalue": lambda self: b"<p>deadline</p>"})()
    report = type("Report", (), {})()

    class FakeIngestionPipeline:
        def process(self, root, bid_id):
            calls["ingestion"] = (root, bid_id)
            return report

    class FakeCorpusStore:
        def __init__(self, path):
            calls["corpus_path"] = path

    class FakeIndexService:
        def __init__(self, store):
            calls["store"] = store

        def update(self, request):
            calls["request"] = request
            return {"indexed": 1, "failed": 0}

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(client_module, "IngestionPipeline", FakeIngestionPipeline)
    monkeypatch.setattr(client_module, "report_dict", lambda value: {"chunks": [{"text": "deadline"}], "status": "complete"})
    monkeypatch.setattr(client_module, "CorpusStore", FakeCorpusStore)
    monkeypatch.setattr(client_module, "IndexService", FakeIndexService)
    monkeypatch.setattr(client_module, "index_path", lambda: tmp_path / "search-index.json")
    def fake_sync(store):
        calls["chroma_store"] = store
        return {"failed": 0}

    monkeypatch.setattr(client_module, "sync_chroma_index", fake_sync, raising=False)

    result = FrontendClient(FrontendConfig(), transport=httpx.Client()).import_bid_files("New Bid", [upload])

    assert calls["ingestion"][1] == result["bid_id"]
    assert calls["store"] is calls["chroma_store"]
    assert result["vector_index"]["failed"] == 0


def test_extraction_job_client_polls_until_result():
    polls = 0

    def handler(request):
        nonlocal polls
        if request.method == "POST":
            return httpx.Response(202, json={"job_id": "job-1", "status": "queued"})
        polls += 1
        if polls == 1:
            return httpx.Response(200, json={"job_id": "job-1", "status": "running"})
        return httpx.Response(200, json={
            "job_id": "job-1",
            "status": "completed",
            "result": {"run_id": "run-1", "status": "completed", "output": {"fields": {}}},
        })

    transport = httpx.Client(transport=httpx.MockTransport(handler))
    config = FrontendConfig(job_poll_interval_seconds=0, job_max_wait_seconds=1)
    client = FrontendClient(config, transport=transport)
    started = client.start_extraction_job(ExtractionRequest(bid_id="Bid1"))
    updates = []

    result = client.wait_for_extraction_job(started["job_id"], updates.append)

    assert result["run_id"] == "run-1"
    assert [update["status"] for update in updates] == ["running", "completed"]
    assert polls == 2
    transport.close()


def test_extraction_job_wait_timeout_is_retryable_without_resubmission():
    transport = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(202, json={"job_id": "job-1", "status": "queued"})
        if request.method == "POST"
        else httpx.Response(200, json={"job_id": "job-1", "status": "running"})
    ))
    client = FrontendClient(
        FrontendConfig(job_poll_interval_seconds=0, job_max_wait_seconds=0),
        transport=transport,
    )
    started = client.start_extraction_job(ExtractionRequest(bid_id="Bid1"))

    with pytest.raises(FrontendRequestError) as error:
        client.wait_for_extraction_job(started["job_id"])

    assert error.value.error.category == "timeout"
    assert error.value.error.retryable is True
    transport.close()


def test_expired_extraction_job_is_not_resumable():
    transport = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(404, json={"detail": {"code": "job_not_found"}})
    ))
    client = FrontendClient(FrontendConfig(), transport=transport)

    with pytest.raises(FrontendRequestError) as error:
        client.get_extraction_job("expired-job")

    assert error.value.error.retryable is False
    assert "Start a new extraction" in error.value.error.message
    transport.close()
