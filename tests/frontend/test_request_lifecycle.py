from src.frontend.state import FrontendSession


def test_new_request_replaces_stale_result():
    state = FrontendSession(response={"answer": "old"}, request_state="success")
    state.begin_request("qa")
    assert state.response is None
    assert state.request_state == "loading"
