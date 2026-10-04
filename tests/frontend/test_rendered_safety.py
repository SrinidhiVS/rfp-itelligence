from src.frontend.views import extraction_view


def test_rendered_extraction_keeps_unsupported_claims_out():
    view = extraction_view({"output": {"fields": {"Due Date": {"value": None, "confidence": 0.0, "status": "not_found", "notes": "Not found in documents", "citations": []}}, "addendum_changes": [], "validation": []}, "diagnostics": [], "trace_reference": None, "evaluation": {}})
    assert view["fields"]["Due Date"]["value"] is None
    assert view["fields"]["Due Date"]["status"] == "not_found"
