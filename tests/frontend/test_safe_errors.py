from src.frontend.views import answer_view


def test_rendered_view_does_not_include_secret_metadata():
    view = answer_view({"output": {"answer": "Not found in documents", "found": False, "citations": [], "evidence_by_bid": {}}, "diagnostics": [], "trace_reference": None})
    assert "api_key" not in str(view).lower()
    assert "secret" not in str(view).lower()
