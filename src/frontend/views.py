"""Normalize analysis responses and render cited results in Streamlit views."""

from __future__ import annotations

import re
from typing import Any

from src.extraction.fields import CANONICAL_FIELDS


def citation_rows(citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert API citation mappings into display rows.

    Args:
        citations: Citation objects with file, bid, page, locator, or location.

    Returns:
        List of dictionaries with ``File``, ``Page/location``, and ``Bid``
        display columns.
    """
    rows = []
    for item in citations:
        page = item.get("page")
        if page is None:
            page = item.get("page_number")
        location = item.get("location")
        if page is not None:
            display_location = page
        else:
            display_location = (
                _format_location(location)
                or _format_location(item.get("locator"))
                or _format_location(item.get("source_locator"))
                or "Unavailable"
            )
        rows.append({
            "File": item.get("file", "Unknown"),
            "Page/location": display_location,
            "Bid": item.get("bid_id", "Unknown"),
        })
    return rows


def _format_location(value: Any) -> str | None:
    """Flatten nested locator text into a readable section path."""
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, (list, tuple)):
        parts = [part for item in value if (part := _format_location(item))]
        return " > ".join(parts) or None
    if isinstance(value, dict):
        for key in ("heading_path", "section_path", "section_title", "heading", "section", "title", "label", "location", "path"):
            if key in value and (formatted := _format_location(value[key])):
                return formatted
        parts = [
            item.strip()
            for item in value.values()
            if isinstance(item, str) and item.strip()
        ]
        return " > ".join(parts) or None
    if value is not None:
        return str(value)
    return None


def answer_view(
    response: dict[str, Any], selected_bid_ids: list[str] | None = None
) -> dict[str, Any]:
    """Normalize an API QA response for rendering and selected-bid comparison.

    Args:
        response: Public analysis response mapping with an ``output`` object.
        selected_bid_ids: Optional display scope; missing bids receive empty
            evidence arrays.

    Returns:
        View mapping with answer/found/claims/change log, display citation rows,
        evidence grouped by bid, missing-evidence bid IDs, diagnostics, and
        trace reference.
    """
    output = response.get("output", {})
    evidence_by_bid = output.get("evidence_by_bid", {}) or {}
    if selected_bid_ids is not None:
        evidence_by_bid = {
            bid_id: evidence_by_bid.get(bid_id, []) or []
            for bid_id in selected_bid_ids
        }
    claims = output.get("claims", []) or []
    answer = output.get("answer") or "Not found in documents"
    if len(answer) > 600 and claims:
        bid_ids = list(dict.fromkeys(claim.get("bid_id") for claim in claims if claim.get("bid_id")))
        scope = f" for {', '.join(bid_ids)}" if bid_ids else ""
        claim_label = "claim" if len(claims) == 1 else "claims"
        answer = f"Found {len(claims)} cited {claim_label}{scope}. Expand a claim below to review its supporting details."
    return {
        "answer": answer,
        "found": bool(output.get("found")),
        "claims": claims,
        "change_log": output.get("change_log", []) or [],
        "citations": citation_rows(output.get("citations", [])),
        "evidence_by_bid": evidence_by_bid,
        "missing_evidence_bids": [bid_id for bid_id, items in evidence_by_bid.items() if not items],
        "diagnostics": response.get("diagnostics", []),
        "trace_reference": response.get("trace_reference"),
    }


def extraction_view(response: dict[str, Any]) -> dict[str, Any]:
    """Normalize extraction output to canonical fields and validation counts.

    Args:
        response: Public analysis response mapping.

    Returns:
        Mapping with every canonical field (missing entries get unavailable
        defaults), extra fields, changes, validation data/counts, summary,
        diagnostics, trace reference, and evaluation.
    """
    output = response.get("output", {})
    response_fields = output.get("fields", {}) or {}
    fields = {
        name: response_fields.get(
            name,
            {
                "value": None,
                "confidence": None,
                "status": "unavailable",
                "notes": "Field was not included in the response.",
                "citations": [],
            },
        )
        for name in CANONICAL_FIELDS
    }
    extra_fields = {
        name: field
        for name, field in response_fields.items()
        if name not in CANONICAL_FIELDS
    }
    validation = output.get("validation", []) or []
    return {
        "fields": fields,
        "extra_fields": extra_fields,
        "addendum_changes": output.get("addendum_changes", []),
        "validation": validation,
        "validation_counts": _validation_counts(fields, validation),
        "summary": output.get("summary", ""),
        "diagnostics": response.get("diagnostics", []),
        "trace_reference": response.get("trace_reference"),
        "evaluation": response.get("evaluation", {}),
    }


def _validation_counts(
    fields: dict[str, dict[str, Any]], validation: list[Any]
) -> dict[str, Any] | None:
    """Aggregate normalized validation statuses across known canonical fields."""
    normalized_statuses = {
        "passed": "passed",
        "supported": "passed",
        "rejected": "failed",
        "failed": "failed",
        "not_found": "not_found",
        "review_required": "review_required",
    }
    validation_statuses: dict[str, set[str]] = {}
    for result in validation:
        if not isinstance(result, dict) or result.get("scope") != "field":
            continue
        field_name = result.get("field")
        status = normalized_statuses.get(result.get("status"))
        if field_name in fields and status:
            validation_statuses.setdefault(field_name, set()).add(status)

    counts = {name: 0 for name in ("passed", "failed", "not_found", "review_required")}
    known_fields = 0
    for field_name, field in fields.items():
        explicit = validation_statuses.get(field_name, set())
        if len(explicit) == 1:
            status = next(iter(explicit))
        elif len(explicit) > 1:
            status = "review_required"
        else:
            status = normalized_statuses.get(field.get("status"))
        if status:
            counts[status] += 1
            known_fields += 1

    if known_fields == 0:
        return None
    return {
        **counts,
        "known_fields": known_fields,
        "total_fields": len(CANONICAL_FIELDS),
        "complete": known_fields == len(CANONICAL_FIELDS),
    }


def render_run_status(st, response: dict[str, Any]) -> None:
    """Render completed/partial/review/failed response status in Streamlit."""
    status = response.get("status")
    labels = {
        "completed": "Complete",
        "partial": "Partial",
        "review_required": "Review required",
        "failed": "Failed",
    }
    label = labels.get(status, "Status unavailable")
    message = f"Run status: {label}"
    if status == "completed":
        st.success(message)
    elif status in {"partial", "review_required"}:
        st.warning(message)
    elif status == "failed":
        st.error(message)
    else:
        st.info(message)


def question_bid_warning(
    question: str, selected_bid_ids: list[str], available_bid_ids: list[str]
) -> str | None:
    """Warn when a question explicitly names only an unselected available bid."""
    mentioned = {
        bid_id.casefold(): bid_id
        for bid_id in available_bid_ids
        if re.search(rf"(?<!\w){re.escape(bid_id)}(?!\w)", question, re.IGNORECASE)
    }
    selected = {bid_id.lower() for bid_id in selected_bid_ids}
    mismatched = set(mentioned) - selected if selected else set()
    if mismatched and not set(mentioned).intersection(selected):
        display_mismatched = [mentioned[bid_id] for bid_id in sorted(mismatched)]
        return f"Your question mentions {', '.join(display_mismatched)}, but the selected bids are {', '.join(selected_bid_ids)}. Select the matching bid or select both bids for a comparison."
    return None


def render_answer(
    st, response: dict[str, Any], selected_bid_ids: list[str] | None = None
) -> None:
    """Render answer text, claims, citations, changes, evidence, and diagnostics."""
    render_run_status(st, response)
    view = answer_view(response, selected_bid_ids)
    if not view["found"]:
        st.info("Not found in documents")
    else:
        st.text(view["answer"])
    if view["found"] and view["claims"]:
        st.subheader("Evidence-backed answer")
        claim_count = len(view["claims"])
        claim_label = "claim" if claim_count == 1 else "claims"
        with st.expander(f"Supporting evidence ({claim_count} {claim_label})", expanded=False):
            for claim in view["claims"]:
                text = str(claim.get("text", "")).strip()
                bid_id = claim.get("bid_id", "Bid")
                label = f"{bid_id} · {_preview(text, 120)}"
                with st.expander(label, expanded=claim_count == 1 and len(text) <= 240):
                    st.write(text)
                    claim_citations = citation_rows(claim.get("citations", []))
                    if claim_citations:
                        render_citations(st, claim_citations)
    if view["citations"] and not view["claims"]:
        st.subheader("Citations")
        render_citations(st, view["citations"])
    if view["change_log"]:
        st.subheader("Detected changes")
        for change in view["change_log"]:
            field = change.get("field", "Requirement")
            previous = _preview(_display_value(change.get("previous_value")), 90)
            current = _preview(_display_value(change.get("new_value")), 90)
            addendum = change.get("addendum_number")
            review = " · Review required" if change.get("review_required") else ""
            with st.expander(f"{field}: {previous} -> {current} · Addendum {addendum or 'unknown'}{review}"):
                st.write(f"Previous: {_display_value(change.get('previous_value')) or 'Unavailable'}")
                st.write(f"Current: {_display_value(change.get('new_value')) or 'Unavailable'}")
                if change.get("reason"):
                    st.caption(change["reason"])
                citations = citation_rows(change.get("citations", []))
                if citations:
                    render_citations(st, citations)
    for bid_id, evidence in view["evidence_by_bid"].items():
        if not evidence:
            st.info(f"No evidence returned for {bid_id}.")
            continue
        with st.expander(f"Evidence: {bid_id}", expanded=False):
            for item in evidence:
                passage = str(item.get("record", {}).get("text", ""))
                st.text(_preview(passage, 500))
    render_diagnostics(st, view["diagnostics"])
    if view["trace_reference"]:
        st.caption(f"Trace: {view['trace_reference']}")


def render_extraction(st, response: dict[str, Any]) -> None:
    """Render canonical fields, item values, citations, changes, and validation."""
    render_run_status(st, response)
    view = extraction_view(response)
    st.subheader("Extracted fields")
    for name, field in view["fields"].items():
        status = field.get("status", "unknown")
        confidence = field.get("confidence")
        confidence_label = f"{confidence:.2f}" if isinstance(confidence, (int, float)) else "unavailable"
        label = f"{name} · {status} · confidence {confidence_label}"
        value = field.get("value")
        expanded = status == "supported" and not isinstance(value, list) and len(_display_value(value)) <= 240
        with st.expander(label, expanded=expanded):
            if isinstance(value, list):
                render_collection_value(st, value)
            else:
                st.write(value if value is not None else "Unavailable")
            if field.get("notes"):
                st.caption(field["notes"])
            citations = citation_rows(field.get("citations", []))
            if citations:
                render_citations(st, citations)
    if view["extra_fields"]:
        st.subheader("Additional fields")
        for name, field in view["extra_fields"].items():
            with st.expander(name):
                st.write(field.get("value") if field.get("value") is not None else "Unavailable")
                if field.get("notes"):
                    st.caption(field["notes"])
    if view["addendum_changes"]:
        st.subheader("Addendum changes")
        for change in view["addendum_changes"]:
            field_name = change.get("field", "Field")
            previous = _preview(_display_value(change.get("previous_value")), 90)
            current = _preview(_display_value(change.get("current_value", change.get("new_value"))), 90)
            addendum = change.get("addendum_number")
            review = " · Review required" if change.get("review_required") else ""
            with st.expander(f"{field_name}: {previous} -> {current} · Addendum {addendum or 'unknown'}{review}"):
                st.write(f"Previous: {_display_value(change.get('previous_value')) or 'Unavailable'}")
                st.write(f"Current: {_display_value(change.get('current_value', change.get('new_value'))) or 'Unavailable'}")
                if change.get("notes") or change.get("reason"):
                    st.caption(change.get("notes") or change.get("reason"))
                citations = change.get("current_citations") or change.get("citations") or []
                if change.get("controlling_citation"):
                    citations = [*citations, change["controlling_citation"]]
                if citations:
                    render_citations(st, citation_rows(citations))
    st.subheader("Validation")
    counts = view["validation_counts"]
    if counts is None:
        st.info("Validation counts unavailable.")
    else:
        for label, key in (
            ("Passed", "passed"),
            ("Failed", "failed"),
            ("Not found", "not_found"),
            ("Review required", "review_required"),
        ):
            st.write(f"{label}: {counts[key]}")
        if counts["complete"]:
            st.caption(f"Validation outcomes cover all {counts['total_fields']} canonical fields.")
        else:
            st.caption(
                f"Validation counts incomplete: outcomes available for "
                f"{counts['known_fields']} of {counts['total_fields']} canonical fields."
            )
    render_diagnostics(st, view["diagnostics"])
    if view["trace_reference"]:
        st.caption(f"Trace: {view['trace_reference']}")


def render_diagnostics(st, diagnostics: list[Any]) -> None:
    """Render each diagnostic as an error or warning based on severity."""
    for diagnostic in diagnostics:
        message = diagnostic.get("message", str(diagnostic)) if isinstance(diagnostic, dict) else str(diagnostic)
        severity = diagnostic.get("severity", "warning") if isinstance(diagnostic, dict) else "warning"
        (st.error if severity == "error" else st.warning)(message)


def render_citations(st, citations: list[dict[str, Any]]) -> None:
    """Render citation rows as file, page/location, and bid text."""
    for citation in citations:
        st.text(
            f"File: {citation['File']}\n"
            f"Page/location: {citation['Page/location']}\n"
            f"Bid: {citation['Bid']}"
        )


def render_collection_value(st, items: list[Any]) -> None:
    """Render collection field values and attributes as a Streamlit dataframe."""
    rows = []
    for item in items:
        if isinstance(item, dict):
            value = item.get("value", "")
            attributes = item.get("attributes", {}) or {}
            details = "; ".join(f"{key}: {value}" for key, value in attributes.items())
        else:
            value = item
            details = ""
        rows.append({"Value": str(value), "Details": details})
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.write("Unavailable")


def _display_value(value: Any) -> str:
    """Format scalar/list field values as concise display text."""
    if value is None:
        return ""
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(str(item.get("value", "")))
            else:
                parts.append(str(item))
        return "; ".join(part for part in parts if part)
    return str(value).strip()


def _preview(value: str, limit: int) -> str:
    """Collapse whitespace and truncate a label to the requested character limit."""
    normalized = " ".join(value.split())
    return normalized if len(normalized) <= limit else normalized[: limit - 3].rstrip() + "..."
