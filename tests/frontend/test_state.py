from src.frontend.state import FrontendSession, UiErrorState


def test_session_clears_stale_response_on_new_request():
    session = FrontendSession(response={"old": True}, request_state="success")
    session.begin_request("qa")
    assert session.request_state == "loading"
    assert session.response is None


def test_session_maps_error_state():
    session = FrontendSession()
    session.fail(UiErrorState(category="connection", message="unavailable"))
    assert session.request_state == "error"
    assert session.error.category == "connection"
