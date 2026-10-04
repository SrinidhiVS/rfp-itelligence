import json
from pathlib import Path

from src.frontend.client import FrontendClient, FrontendRequestError
from src.frontend.config import FrontendConfig
from src.frontend.state import QuestionRequest
import httpx


def test_malformed_backend_response_is_user_safe():
    transport = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"bad": True})))
    client = FrontendClient(FrontendConfig(), transport=transport)
    try:
        client.ask(QuestionRequest(question="deadline", bid_ids=["Bid1"]))
    except FrontendRequestError as error:
        assert error.error.category == "malformed_response"
    else:
        raise AssertionError("malformed response was accepted")


def test_fixture_error_payload_is_safe_to_display():
    payload = json.loads(Path("tests/fixtures/frontend/error-response.json").read_text(encoding="utf-8"))
    assert payload["detail"]["code"] == "dependency_error"
    assert "api_key" not in json.dumps(payload).lower()


def test_connection_failure_is_retryable():
    transport = httpx.Client(transport=httpx.MockTransport(lambda request: (_ for _ in ()).throw(httpx.ConnectError("offline"))))
    client = FrontendClient(FrontendConfig(), transport=transport)
    try:
        client.ask(QuestionRequest(question="deadline", bid_ids=["Bid1"]))
    except FrontendRequestError as error:
        assert error.error.retryable is True
    else:
        raise AssertionError("connection failure was not surfaced")
