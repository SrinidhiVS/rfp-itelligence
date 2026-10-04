import pytest
from streamlit.testing.v1 import AppTest

from src.extraction.fields import CANONICAL_FIELDS
from src.frontend.client import FrontendRequestError
from src.frontend.state import UiErrorState


def test_app_test_harness_starts_frontend(app_test):
    assert not app_test.exception
    assert app_test.radio[0].value == "Ask questions"


def test_question_workflow_renders_locator_and_missing_selected_bid(
    app_test, frontend_client
):
    frontend_client.question_response = {
        "run_id": "qa-run",
        "status": "completed",
        "output": {
            "answer": "The deadline is October 30.",
            "found": True,
            "citations": [
                {
                    "file": "bid.html",
                    "page": None,
                    "locator": {"heading_path": ["Submission", "Deadline"]},
                    "bid_id": "Bid1",
                }
            ],
            "evidence_by_bid": {"Bid1": [{"record": {"text": "Deadline is October 30."}}]},
        },
        "diagnostics": [],
        "trace_reference": None,
        "evaluation": {},
    }
    app_test.multiselect[0].set_value(["Bid1", "District-RFP-3"])
    app_test.text_area[0].set_value("What is the deadline?")
    next(button for button in app_test.button if button.label == "Ask").click()
    app_test.run()

    assert not app_test.exception
    citation_text = " ".join(str(element.value) for element in app_test.text)
    assert "Submission" in citation_text
    assert any("No evidence returned for District-RFP-3" in str(item.value) for item in app_test.info)


def test_question_workflow_warns_for_configured_nondefault_bid(app_test):
    app_test.multiselect[0].set_value(["Bid2"])
    app_test.text_area[0].set_value("What is the deadline for District-RFP-3?")
    next(button for button in app_test.button if button.label == "Ask").click()
    app_test.run()

    assert any("District-RFP-3" in str(item.value) for item in app_test.warning)


def test_question_workflow_submits_updated_question_after_previous_answer(
    app_test, frontend_client
):
    app_test.multiselect[0].set_value(["Bid1", "Bid2"])
    app_test.text_area[0].set_value("What is the submission deadline?")
    next(button for button in app_test.button if button.label == "Ask").click()
    app_test.run()

    app_test.text_area[0].set_value("Which affidavits are required for Bid2?")
    app_test.run()
    assert app_test.session_state.question_input == "Which affidavits are required for Bid2?"
    assert app_test.session_state.frontend_session.question == "Which affidavits are required for Bid2?"
    next(button for button in app_test.button if button.label == "Ask").click()
    app_test.run()

    assert frontend_client.questions == [
        "What is the submission deadline?",
        "Which affidavits are required for Bid2?",
    ]


def test_long_claim_answers_render_as_compact_expandable_evidence(app_test, frontend_client, response_factory):
    long_claim = "Bid2 affidavit requirement: " + "ordinary source detail " * 30 + "LONG-AFFIDAVIT-SOURCE-DETAIL"
    frontend_client.question_response = response_factory(
        output={
            "answer": long_claim * 6,
            "found": True,
            "citations": [],
            "claims": [{
                "text": long_claim,
                "bid_id": "Bid2",
                "citations": [{"file": "affidavit.pdf", "page": 1, "bid_id": "Bid2"}],
            }],
            "evidence_by_bid": {"Bid2": [{"record": {"text": long_claim}}]},
        }
    )
    app_test.multiselect[0].set_value(["Bid2"])
    app_test.text_area[0].set_value("Which affidavits are required for Bid2?")
    next(button for button in app_test.button if button.label == "Ask").click()
    app_test.run()

    assert not app_test.exception
    assert any("Bid2" in expander.label for expander in app_test.expander)
    assert all(long_claim * 6 not in str(element.value) for element in app_test.markdown)


def test_long_claim_answers_render_as_compact_expandable_evidence(
    app_test, frontend_client, response_factory
):
    long_claim = "Bid2 affidavit requirement: " + "ordinary source detail " * 30 + "LONG-AFFIDAVIT-SOURCE-DETAIL"
    frontend_client.question_response = response_factory(
        output={
            "answer": long_claim * 5,
            "found": True,
            "citations": [],
            "claims": [{
                "text": long_claim,
                "bid_id": "Bid2",
                "citations": [{"file": "affidavit.pdf", "page": 1, "bid_id": "Bid2"}],
            }],
            "evidence_by_bid": {"Bid2": []},
        }
    )
    app_test.multiselect[0].set_value(["Bid2"])
    app_test.text_area[0].set_value("Which affidavits are required?")
    next(button for button in app_test.button if button.label == "Ask").click()
    app_test.run()

    assert not app_test.exception
    assert any("Bid2" in expander.label for expander in app_test.expander)
    assert all(long_claim * 5 not in str(element.value) for element in app_test.markdown)


def _render_import_result_view():
    import streamlit as st

    from src.frontend.app import render_import_result

    render_import_result(st, st.session_state["import_result"])


def _test_import_result_view(result):
    app = AppTest.from_function(_render_import_result_view)
    app.session_state["import_result"] = result
    return app.run()


def test_import_result_renders_partial_diagnostics_and_index_counters(import_result_factory):
    result = import_result_factory(
        status="incomplete",
        diagnostics=[{"message": "One source could not be parsed", "severity": "warning"}],
        documents=[
            {
                "relative_path": "broken.pdf",
                "status": "failed",
                "diagnostics": [{"message": "Unreadable PDF", "severity": "error"}],
            }
        ],
        index={"indexed": 2, "skipped": 0, "replaced": 0, "removed": 0, "failed": 1},
    )

    app = _test_import_result_view(result)
    rendered = " ".join(
        str(element.value)
        for name in ("success", "warning", "error", "info", "caption", "markdown")
        for element in getattr(app, name)
    )

    assert not app.exception
    assert "Partial" in rendered
    assert "Unreadable PDF" in rendered
    assert "broken.pdf" in rendered
    assert "2" in rendered and "1" in rendered


@pytest.mark.parametrize(
    ("status", "expected_label"),
    [
        ("completed", "Complete"),
        ("partial", "Partial"),
        ("review_required", "Review required"),
        ("failed", "Failed"),
    ],
)
def test_question_workflow_displays_run_status(app_test, frontend_client, response_factory, status, expected_label):
    frontend_client.question_response = response_factory(
        status=status,
        output={"answer": "Result", "found": True, "citations": [], "evidence_by_bid": {"Bid1": [{"record": {"text": "evidence"}}]}},
    )
    app_test.multiselect[0].set_value(["Bid1"])
    app_test.text_area[0].set_value("What is the deadline?")
    next(button for button in app_test.button if button.label == "Ask").click()
    app_test.run()
    rendered = " ".join(
        str(element.value)
        for name in ("success", "warning", "error", "info", "caption", "markdown")
        for element in getattr(app_test, name)
    )

    assert expected_label in rendered


def test_extraction_workflow_displays_review_required_run_status(
    app_test, frontend_client, response_factory
):
    frontend_client.extraction_response = response_factory(
        status="review_required",
        output={"fields": {}, "addendum_changes": [], "validation": []},
    )
    app_test.radio[0].set_value("Review extraction")
    app_test.run()
    next(button for button in app_test.button if button.label == "Extract bid").click()
    app_test.run()
    rendered = " ".join(
        str(element.value)
        for name in ("success", "warning", "error", "info", "caption", "markdown")
        for element in getattr(app_test, name)
    )

    assert "Review required" in rendered


def test_extraction_workflow_renders_canonical_fields_and_validation_counts(
    app_test, frontend_client, response_factory
):
    frontend_client.extraction_response = response_factory(
        output={
            "fields": {
                "Title": {"value": None, "status": "not_found", "citations": []},
                "Bid Number": {"value": "B-1", "status": "supported", "citations": []},
            },
            "addendum_changes": [],
            "validation": [],
        }
    )
    app_test.radio[0].set_value("Review extraction")
    app_test.run()
    next(button for button in app_test.button if button.label == "Extract bid").click()
    app_test.run()
    rendered_fields = [
        element.label.split(" · ")[0]
        for element in app_test.expander
        if element.label.split(" · ")[0] in CANONICAL_FIELDS
    ]
    rendered = " ".join(
        str(element.value)
        for name in ("success", "warning", "error", "info", "caption", "markdown")
        for element in getattr(app_test, name)
    )

    assert rendered_fields == list(CANONICAL_FIELDS)
    assert "Passed: 1" in rendered
    assert "Not found: 1" in rendered


def test_extraction_workflow_marks_missing_validation_counts_unavailable(
    app_test, frontend_client, response_factory
):
    frontend_client.extraction_response = response_factory(
        output={"fields": {}, "addendum_changes": [], "validation": []}
    )
    app_test.radio[0].set_value("Review extraction")
    app_test.run()
    next(button for button in app_test.button if button.label == "Extract bid").click()
    app_test.run()
    rendered = " ".join(
        str(element.value)
        for name in ("success", "warning", "error", "info", "caption", "markdown")
        for element in getattr(app_test, name)
    )

    assert "Validation counts unavailable" in rendered


def test_extraction_timeout_can_resume_same_job_without_resubmitting(
    app_test, frontend_client
):
    frontend_client.extraction_wait_error = FrontendRequestError(
        UiErrorState(category="timeout", message="Polling timed out.", retryable=True)
    )
    app_test.radio[0].set_value("Review extraction")
    app_test.run()
    next(button for button in app_test.button if button.label == "Extract bid").click()
    app_test.run()

    assert frontend_client.extraction_job_start_count == 1
    assert frontend_client.extraction_job_polls == [frontend_client.extraction_job_id]
    assert any(button.label == "Resume extraction" for button in app_test.button)

    frontend_client.extraction_wait_error = None
    next(button for button in app_test.button if button.label == "Resume extraction").click()
    app_test.run()

    assert frontend_client.extraction_job_start_count == 1
    assert frontend_client.extraction_job_polls == [
        frontend_client.extraction_job_id,
        frontend_client.extraction_job_id,
    ]