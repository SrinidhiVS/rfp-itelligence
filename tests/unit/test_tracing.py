from src.agents.tracing import safe_summary


def test_trace_summary_excludes_whole_document_text():
    summary = safe_summary({"text": "entire source", "record_id": "r1"})
    assert "text" not in summary
    assert summary["record_id"] == "r1"
