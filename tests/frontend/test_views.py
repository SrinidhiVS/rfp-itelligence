from src.extraction.fields import CANONICAL_FIELDS
from src.frontend.views import answer_view, citation_rows, extraction_view, question_bid_warning, render_answer


def test_answer_view_preserves_citations_and_bid_groups():
    view = answer_view({"output": {"answer": "answer", "found": True, "citations": [{"file": "x.pdf", "page": 2, "bid_id": "Bid1"}], "evidence_by_bid": {"Bid1": []}}, "diagnostics": [], "trace_reference": "run", "status": "completed", "run_id": "run", "evaluation": {}})
    assert view["citations"][0]["Bid"] == "Bid1"
    assert view["trace_reference"] == "run"


def test_answer_view_summarizes_oversized_prose_and_keeps_claims():
    claim = {"text": "Bid2 affidavit requirement: " + "source detail " * 80, "bid_id": "Bid2", "citations": []}
    view = answer_view({
        "output": {
            "answer": claim["text"] * 6,
            "found": True,
            "claims": [claim],
            "citations": [],
            "evidence_by_bid": {},
        }
    })

    assert view["answer"] == "Found 1 cited claim for Bid2. Expand a claim below to review its supporting details."
    assert view["claims"] == [claim]


def test_render_answer_displays_generated_answer_before_supporting_claims():
    class Expander:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class FakeStreamlit:
        def __init__(self):
            self.text_values = []

        def success(self, message):
            pass

        def markdown(self, value):
            pass

        def subheader(self, value):
            pass

        def expander(self, *args, **kwargs):
            return Expander()

        def write(self, value):
            pass

        def text(self, value):
            self.text_values.append(value)

    st = FakeStreamlit()
    render_answer(st, {
        "status": "completed",
        "output": {
            "answer": "The submission deadline is October 10, 2026.",
            "found": True,
            "claims": [{"text": "Bid1: submission deadline is October 10, 2026.", "bid_id": "Bid1", "citations": []}],
            "citations": [],
            "evidence_by_bid": {},
        },
        "diagnostics": [],
    })

    assert st.text_values == ["The submission deadline is October 10, 2026."]


def test_render_answer_collapses_and_truncates_evidence():
    class Expander:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class FakeStreamlit:
        def __init__(self):
            self.text_values = []
            self.expanders = []

        def success(self, message):
            pass

        def info(self, message):
            pass

        def subheader(self, value):
            pass

        def expander(self, label, **kwargs):
            self.expanders.append((label, kwargs))
            return Expander()

        def text(self, value):
            self.text_values.append(value)

        def write(self, value):
            pass

        def caption(self, value):
            pass

    passage = "Source detail " * 100
    st = FakeStreamlit()
    render_answer(st, {
        "status": "completed",
        "output": {
            "answer": "The submission deadline is October 10, 2026.",
            "found": True,
            "claims": [],
            "citations": [],
            "evidence_by_bid": {"Bid1": [{"record": {"text": passage}}]},
        },
        "diagnostics": [],
    })

    evidence_expander = next(options for label, options in st.expanders if label == "Evidence: Bid1")
    evidence_text = st.text_values[-1]
    assert evidence_expander == {"expanded": False}
    assert evidence_text.endswith("...")
    assert len(evidence_text) <= 500
    assert passage not in evidence_text


def test_extraction_view_preserves_fields_and_changes():
    view = extraction_view({"output": {"fields": {"Due Date": {"value": None, "confidence": 0.0, "status": "not_found", "notes": "Not found in documents", "citations": []}}, "addendum_changes": [{"field": "Due Date"}], "validation": []}, "diagnostics": [], "trace_reference": None, "evaluation": {}, "status": "completed", "run_id": "run"})
    assert view["fields"]["Due Date"]["confidence"] == 0.0
    assert view["addendum_changes"]


def test_extraction_view_accepts_null_confidence():
    view = extraction_view({"output": {"fields": {"Due Date": {"value": None, "confidence": None, "status": "not_found", "notes": "missing", "citations": []}}, "addendum_changes": [], "validation": []}, "diagnostics": [], "trace_reference": None, "evaluation": {}})
    assert view["fields"]["Due Date"]["confidence"] is None


def test_question_bid_warning_detects_selected_bid_mismatch():
    warning = question_bid_warning("What is the deadline for Bid1?", ["Bid2"], ["Bid1", "Bid2"])
    assert warning and "Bid1" in warning and "Bid2" in warning


def test_citation_rows_uses_page_then_readable_location_fallback():
    rows = citation_rows([
        {"file": "page.pdf", "page": 4, "location": "Section A", "bid_id": "Bid1"},
        {"file": "bid.html", "locator": {"heading_path": ["Submission", "Deadline"]}, "bid_id": "Bid2"},
        {"file": "unknown.html", "locator": {}, "bid_id": "Bid3"},
    ])

    assert rows[0]["Page/location"] == 4
    assert "Submission" in rows[1]["Page/location"]
    assert "Deadline" in rows[1]["Page/location"]
    assert rows[2]["Page/location"] == "Unavailable"


def test_answer_view_includes_selected_bids_without_evidence():
    view = answer_view(
        {
            "output": {
                "answer": "Answer",
                "found": True,
                "citations": [],
                "evidence_by_bid": {"Bid1": [{"record": {"text": "evidence"}}], "Unselected": []},
            }
        },
        selected_bid_ids=["Bid1", "Bid2"],
    )

    assert list(view["evidence_by_bid"]) == ["Bid1", "Bid2"]
    assert view["evidence_by_bid"]["Bid2"] == []
    assert view["missing_evidence_bids"] == ["Bid2"]


def test_question_bid_warning_uses_configured_bid_ids():
    warning = question_bid_warning(
        "What is the deadline for District-RFP-3?",
        ["Bid2"],
        ["Bid1", "Bid2", "District-RFP-3"],
    )

    assert warning and "District-RFP-3" in warning and "Bid2" in warning


def test_question_bid_warning_ignores_unconfigured_bid_ids():
    warning = question_bid_warning(
        "What is the deadline for Bid1?",
        ["Bid2"],
        ["Bid2", "District-RFP-3"],
    )

    assert warning is None


def test_extraction_view_uses_canonical_order_and_separates_extra_fields():
    view = extraction_view(
        {
            "output": {
                "fields": {
                    "Product": {"value": "Laptop", "status": "supported"},
                    "Title": {"value": "Solicitation", "status": "supported"},
                    "Unexpected field": {"value": "Extra", "status": "supported"},
                }
            }
        }
    )

    assert list(view["fields"]) == list(CANONICAL_FIELDS)
    assert view["fields"]["Bid Number"]["status"] == "unavailable"
    assert view["extra_fields"] == {"Unexpected field": {"value": "Extra", "status": "supported"}}


def test_extraction_view_counts_explicit_status_once_per_field():
    view = extraction_view(
        {
            "output": {
                "fields": {
                    "Bid Number": {"value": "B-1", "status": "supported"},
                    "Title": {"value": None, "status": "not_found"},
                    "Due Date": {"value": "Oct 30", "status": "supported"},
                    "Bid Submission Type": {"value": None, "status": "review_required"},
                    "Unexpected field": {"value": None, "status": "failed"},
                },
                "validation": [
                    {"scope": "field", "field": "Due Date", "status": "rejected"},
                    {"scope": "run", "field": None, "status": "passed"},
                ],
            }
        }
    )

    assert view["validation_counts"] == {
        "passed": 1,
        "failed": 1,
        "not_found": 1,
        "review_required": 1,
        "known_fields": 4,
        "total_fields": 20,
        "complete": False,
    }


def test_extraction_view_marks_counts_unavailable_without_status_data():
    view = extraction_view({"output": {"fields": {}, "validation": []}})

    assert view["validation_counts"] is None
