"""Run the Streamlit RFP question-answering and extraction review interface."""

from __future__ import annotations

from textwrap import dedent

import streamlit as st
from src.frontend.client import FrontendClient, FrontendRequestError
from src.frontend.config import FrontendConfig
from src.frontend.state import ExtractionRequest, FrontendSession, QuestionRequest
from src.frontend.views import question_bid_warning, render_answer, render_diagnostics, render_extraction


@st.cache_resource
def get_client() -> FrontendClient:
    """Return a cached API client configured from frontend environment values."""
    return FrontendClient(FrontendConfig.from_env())


def session_state() -> FrontendSession:
    """Initialize and return the validated per-browser frontend session model."""
    if "frontend_session" not in st.session_state:
        st.session_state.frontend_session = FrontendSession()
    return st.session_state.frontend_session


def main() -> None:
    """Render the app shell, backend readiness, import, QA, and extraction flows."""
    st.set_page_config(page_title="RFP Intelligence", layout="wide")
    st.markdown(
        dedent(
            """
        <style>
        .stMainBlockContainer, [data-testid="stAppViewBlockContainer"] {
            max-width: 1280px;
            padding-top: 1.5rem;
            padding-bottom: 2.5rem;
        }
        [data-testid="stMarkdownContainer"] p,
        [data-testid="stText"] {
            line-height: 1.45;
            overflow-wrap: anywhere;
        }
        </style>
            """
        ),
        unsafe_allow_html=True,
    )
    session = session_state()
    client = get_client()
    st.title("RFP Intelligence")
    st.caption("Source-grounded bid questions and structured extraction review")

    try:
        health = client.health()
        semantic = health.get("semantic_search", {})
        if semantic.get("semantic_enabled"):
            st.sidebar.success("Semantic search: ready")
        else:
            st.sidebar.info("Semantic search: keyword fallback active")
            if semantic.get("semantic_diagnostic"):
                st.sidebar.caption(str(semantic["semantic_diagnostic"])[:240])
    except FrontendRequestError as exc:
        st.sidebar.warning(exc.error.message)

    available_bid_ids = list(st.session_state.get("available_bid_ids", client.config.bid_ids))
    with st.sidebar.expander("Import new bid folder", expanded=False):
        folder_name = st.text_input("Bid folder name", key="import_folder_name")
        uploaded_files = st.file_uploader("HTML/PDF files", type=["html", "htm", "pdf"], accept_multiple_files=True, key="import_files")
        if st.button("Import and index", disabled=not folder_name or not uploaded_files, key="import_bid"):
            with st.spinner("Importing and indexing bid..."):
                try:
                    result = client.import_bid_files(folder_name, uploaded_files)
                    available_bid_ids = sorted(set(available_bid_ids + [result["bid_id"]]))
                    st.session_state.available_bid_ids = available_bid_ids
                    render_import_result(st, result)
                except FrontendRequestError as exc:
                    st.error(exc.error.message)
                except Exception as exc:
                    st.error(f"Import failed: {exc}")

    mode = st.radio("Workflow", ["Ask questions", "Review extraction"], horizontal=True)
    if mode == "Ask questions":
        render_question_flow(st, client, session, available_bid_ids)
    else:
        render_extraction_flow(st, client, session, available_bid_ids)


def render_import_result(st, result: dict) -> None:
    """Display ingestion status, indexing counts, and source diagnostics."""
    report = result.get("report") or {}
    report_status = report.get("status", "unknown")
    status_labels = {
        "complete": "Complete",
        "incomplete": "Partial",
        "empty": "Empty",
        "failed": "Failed",
    }
    status_label = status_labels.get(report_status, "Status unavailable")
    bid_id = result.get("bid_id", "Unknown")
    message = f"Imported bid {bid_id}. Import status: {status_label}."
    if report_status == "complete":
        st.success(message)
    elif report_status == "failed":
        st.error(message)
    else:
        st.warning(message)

    index = result.get("index") or {}
    counters = [
        (label, key)
        for label, key in (
            ("Indexed", "indexed"),
            ("Skipped", "skipped"),
            ("Replaced", "replaced"),
            ("Removed", "removed"),
            ("Failed", "failed"),
        )
        if key in index
    ]
    if counters:
        st.caption("Index counts: " + ", ".join(f"{label} {index[key]}" for label, key in counters))
    if index.get("failed", 0):
        st.warning(f"Indexing status: Partial; {index['failed']} source groups failed to index.")

    vector_index = result.get("vector_index") or {}
    if vector_index:
        if vector_index.get("failed", 0):
            st.warning("Chroma vector sync failed: " + "; ".join(vector_index.get("diagnostics", [])))
        else:
            st.caption(
                "Chroma vectors: "
                f"embedded {vector_index.get('embedded', 0)}, "
                f"unchanged scopes {vector_index.get('unchanged', 0)}"
            )

    diagnostics = list(report.get("diagnostics") or [])
    for document in report.get("documents") or []:
        document_status = document.get("status")
        source_path = document.get("relative_path") or document.get("file_name") or "Unknown source"
        if document_status and document_status not in {"parsed", "complete"}:
            st.warning(f"{source_path}: {document_status}")
        for diagnostic in document.get("diagnostics") or []:
            if isinstance(diagnostic, dict):
                diagnostic = {**diagnostic, "message": f"{source_path}: {diagnostic.get('message', 'Processing issue')}"}
            else:
                diagnostic = f"{source_path}: {diagnostic}"
            diagnostics.append(diagnostic)
    render_diagnostics(st, diagnostics)


def render_question_flow(st, client: FrontendClient, session: FrontendSession, available_bid_ids: list[str]) -> None:
    """Render bid selection/question form and submit a source-grounded QA call."""
    selected = st.multiselect(
        "Bids",
        available_bid_ids,
        default=session.selected_bid_ids[:1],
        key="selected_bid_ids",
    )
    session.selected_bid_ids = selected
    if "question_input" not in st.session_state:
        st.session_state.question_input = session.question
    question = st.text_area(
        "Question",
        placeholder="What is the final submission deadline?",
        key="question_input",
    )
    session.question = question
    if st.button("Ask", type="primary", disabled=session.request_state == "loading"):
        if not selected:
            st.warning("Select at least one bid.")
            return
        warning = question_bid_warning(question, selected, available_bid_ids)
        if warning:
            st.warning(warning)
            return
        session.begin_request("qa")
        with st.spinner("Searching bid evidence..."):
            try:
                session.complete(client.ask(QuestionRequest(question=question, bid_ids=selected)))
            except FrontendRequestError as exc:
                session.fail(exc.error)
    if session.request_state == "error" and session.error:
        st.error(session.error.message)
        if session.error.details:
            st.caption(session.error.details)
    elif session.response:
        render_answer(st, session.response, session.selected_bid_ids)


def render_extraction_flow(st, client: FrontendClient, session: FrontendSession, available_bid_ids: list[str]) -> None:
    """Render bid extraction controls, queue a job, and resume polling on timeout."""
    selected_index = (
        available_bid_ids.index(session.selected_bid_ids[0])
        if session.selected_bid_ids and session.selected_bid_ids[0] in available_bid_ids
        else 0
    )
    selected = st.selectbox("Bid", available_bid_ids, index=selected_index, key="extraction_bid_selector")
    session.selected_bid_ids = [selected]
    if st.button("Extract bid", type="primary", disabled=session.request_state == "loading"):
        session.begin_request("extraction")
        try:
            job = client.start_extraction_job(ExtractionRequest(bid_id=selected))
            session.active_job_id = job["job_id"]
            session.complete(_poll_extraction_job(st, client, job["job_id"]))
        except FrontendRequestError as exc:
            session.fail(exc.error)
    if session.request_state == "error" and session.error:
        st.error(session.error.message)
        if session.error.details:
            st.caption(session.error.details)
        if session.active_job_id and session.error.retryable:
            if st.button("Resume extraction", key="resume_extraction"):
                session.request_state = "loading"
                session.error = None
                try:
                    session.complete(_poll_extraction_job(st, client, session.active_job_id))
                except FrontendRequestError as exc:
                    session.fail(exc.error)
    elif session.response:
        render_extraction(st, session.response)


def _poll_extraction_job(st, client: FrontendClient, job_id: str) -> dict:
    """Poll one extraction job while updating a Streamlit progress status.

    Args:
        st: Streamlit module/interface used for status rendering.
        client: Frontend HTTP client implementing job polling.
        job_id: Existing queued/running job identifier.

    Returns:
        Terminal extraction result mapping.

    Raises:
        FrontendRequestError: If polling fails, times out, or the job fails.
    """
    labels = {
        "queued": "Queued",
        "running": "Running",
        "completed": "Complete",
        "partial": "Partial",
        "review_required": "Review required",
        "failed": "Failed",
    }
    with st.status(f"Extraction queued · {job_id[:8]}", expanded=False) as progress:
        def on_update(job: dict) -> None:
            """Update progress label/state from one serialized job status."""
            status = job.get("status", "unknown")
            is_active = status in {"queued", "running"}
            progress.update(
                label=f"Extraction {labels.get(status, 'in progress')} · {job_id[:8]}",
                state="running" if is_active else "error" if status == "failed" else "complete",
                expanded=is_active,
            )

        try:
            result = client.wait_for_extraction_job(job_id, on_update=on_update)
        except FrontendRequestError:
            progress.update(label=f"Extraction paused · {job_id[:8]}", state="error", expanded=True)
            raise
        status = result.get("status", "completed")
        progress.update(
            label=f"Extraction {labels.get(status, 'finished')} · {job_id[:8]}",
            state="error" if status == "failed" else "complete",
            expanded=False,
        )
        return result


if __name__ == "__main__":
    main()
