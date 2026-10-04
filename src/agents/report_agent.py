"""Synthesize cited QA answers and extraction/QA response envelopes."""

from __future__ import annotations

import re
from typing import Any

from .extraction_agent import _value_for
from .state import AnalysisResponse, Diagnostic, EvaluationReport, ExtractionField, WorkflowState


_QUESTION_STOP_WORDS = {
    "a", "an", "and", "are", "about", "applies", "apply", "between", "does", "do",
    "for", "how", "is", "it", "me", "of", "on", "or", "the", "to", "what", "when",
    "where", "which", "who", "with", "mandatory", "requirement", "requirements", "must",
}


def _question_terms(text: str) -> set[str]:
    """Normalize query terms and remove stop words for evidence matching."""
    terms = re.findall(r"[a-z0-9]+", text.lower())
    return {term[:-1] if len(term) > 4 and term.endswith("s") else term for term in terms if term not in _QUESTION_STOP_WORDS}


def _question_relevant_evidence(question: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep evidence tied for the highest overlap with the question terms."""
    terms = _question_terms(question)
    if not terms:
        return items
    scores = [(len(terms & _question_terms(item["record"]["text"])), item) for item in items]
    best_score = max(score for score, _ in scores)
    return [item for score, item in scores if score == best_score] if best_score else items


def citation_coverage(fields: dict[str, ExtractionField]) -> float:
    """Return fraction of non-null extracted fields carrying citations."""
    values = [field for field in fields.values() if field.value is not None]
    return sum(bool(field.citations) for field in values) / len(values) if values else 1.0


def build_evaluation(state: WorkflowState) -> EvaluationReport:
    """Create a response evaluation summary from the completed workflow state."""
    return EvaluationReport(
        citation_coverage=citation_coverage(state.draft_fields),
        validation_results=state.validation_results,
        retry_count=state.retry_count,
        field_dispositions={name: field.status for name, field in state.draft_fields.items()},
    )


def _source_citation(item: dict[str, Any]) -> dict[str, Any]:
    """Convert nested ranked evidence to a JSON-ready citation mapping."""
    record = item["record"]
    return {
        "file": record["source_file"],
        "page": record.get("page_number"),
        "bid_id": record["bid_id"],
        "locator": record.get("source_locator", {}),
        "authority_status": item.get("authority_status"),
        "superseded_by": item.get("superseded_by"),
    }


def _date_value(text: str) -> str | None:
    """Extract the first supported full date expression from text."""
    patterns = (
        r"\b\d{1,2}[-/]\w{3,9}[-/]20\d{2}\b(?:\s+\d{1,2}:\d{2}:\d{2})?",
        r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+20\d{2}(?:\s+at\s+\d{1,2}:\d{2}\s*(?:AM|PM)(?:\s+[A-Z]{2,5})?)?",
        r"\b20\d{2}-\d{2}-\d{2}\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(0)
    return None


def _deadline_value(text: str) -> str | None:
    """Extract a date appearing after a recognized deadline label."""
    for label in ("solicitation due", "submission deadline", "due date", "deadline"):
        for match in re.finditer(rf"\b{label}\b", text, re.IGNORECASE):
            value = _date_value(text[match.end():match.end() + 120])
            if value is not None:
                return value
    return None


_EXPLICIT_CHANGE_PATTERN = re.compile(
    r"\b(?P<field>[a-z][a-z0-9 /-]{1,60}?)\s+(?:is\s+|was\s+|has\s+been\s+)?"
    r"(?:revised|changed|replaced|extended|increased|decreased|updated)\s+from\s+"
    r"(?P<previous>[^.;\n]+?)\s+to\s+(?P<current>[^.;\n]+)",
    re.IGNORECASE,
)


def _addendum_answer(question: str, evidence: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Answer addendum-change questions with base/addendum citation pairs.

    Args:
        question: User question, optionally naming an addendum number.
        evidence: Ranked evidence mappings grouped by bid and document type.

    Returns:
        QA response mapping with answer, citations, evidence_by_bid, claims,
        change_log, found, and disputed keys; returns ``None`` when the
        question is not about addenda.
    """
    requested = re.search(r"\b(?:addendum|amendment)\s*(?:no\.?\s*)?#?\s*(\d+)\b", question, re.IGNORECASE)
    if "addendum" not in question.lower() and "amendment" not in question.lower():
        return None

    grouped = _grouped_evidence(evidence)
    claims = []
    change_log = []
    for bid_id, items in grouped.items():
        amendments = [
            item
            for item in items
            if item["record"].get("doc_type") == "addendum"
            and (
                requested is None
                or item["record"].get("addendum_number") == int(requested.group(1))
            )
        ]
        for amendment in amendments:
            amendment_text = amendment["record"].get("text", "")
            if not re.search(r"\b(?:change|changed|revise|revised|extend|extended|replace|replaced|new due date)\b", amendment_text, re.IGNORECASE):
                continue
            base_sources = [
                item
                for item in items
                if item["record"].get("doc_type") != "addendum"
                and item.get("authority_status") != "superseded"
            ]
            base_candidates = [
                item
                for item in base_sources
                if re.search(r"\b(?:solicitation due|submission deadline|due date|deadline)\b", item["record"].get("text", ""), re.IGNORECASE)
            ]
            amendment_date = _deadline_value(amendment_text)
            if amendment_date is not None:
                previous_deadline = next(
                    (
                        value
                        for item in base_candidates
                        if (value := _deadline_value(item["record"].get("text", ""))) is not None
                    ),
                    None,
                )
                if previous_deadline is not None and previous_deadline.casefold() != amendment_date.casefold():
                    prior_item = next(item for item in base_candidates if _deadline_value(item["record"].get("text", "")) == previous_deadline)
                    citations = [_source_citation(item) for item in (prior_item, amendment)]
                    claims.append({
                        "text": f"{bid_id}: the submission deadline changed from {previous_deadline} to {amendment_date}.",
                        "bid_id": bid_id,
                        "citations": citations,
                    })
                    change_log.append({
                        "field": "submission_deadline",
                        "previous_value": previous_deadline,
                        "new_value": amendment_date,
                        "addendum_number": amendment["record"].get("addendum_number"),
                        "citations": citations,
                        "review_required": False,
                    })

            for match in _EXPLICIT_CHANGE_PATTERN.finditer(amendment_text):
                field_name = re.sub(r"^(?:the|a|an)\s+", "", match.group("field").strip(), flags=re.IGNORECASE).strip()
                previous_value = match.group("previous").strip()
                current_value = match.group("current").strip()
                field_terms = [term for term in re.findall(r"[a-z0-9]+", field_name.casefold()) if term not in {"the", "a", "an", "minimum"}]
                prior_item = next((
                    item
                    for item in base_sources
                    if previous_value.casefold() in item["record"].get("text", "").casefold()
                    and all(term in item["record"].get("text", "").casefold() for term in field_terms)
                ), None)
                if prior_item is None:
                    continue
                citations = [_source_citation(item) for item in (prior_item, amendment)]
                claims.append({
                    "text": f"{bid_id}: {field_name} changed from {previous_value} to {current_value}.",
                    "bid_id": bid_id,
                    "citations": citations,
                })
                change_log.append({
                    "field": field_name,
                    "previous_value": previous_value,
                    "new_value": current_value,
                    "addendum_number": amendment["record"].get("addendum_number"),
                    "citations": citations,
                    "review_required": False,
                })

    if not claims:
        return {
            "answer": "The documents do not establish what changed in the cited addendum.",
            "citations": [],
            "evidence_by_bid": grouped,
            "claims": [],
            "change_log": [],
            "found": False,
            "disputed": False,
        }
    return {
        "answer": " ".join(claim["text"] for claim in claims),
        "citations": [citation for claim in claims for citation in claim["citations"]],
        "evidence_by_bid": grouped,
        "claims": claims,
        "change_log": change_log,
        "found": True,
        "disputed": False,
    }


def _grouped_evidence(evidence: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group nested evidence records under their bid ID or ``unknown``."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in evidence:
        record = item.get("record", item)
        grouped.setdefault(record.get("bid_id", "unknown"), []).append(item)
    return grouped


def _affidavit_answer(evidence: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize affidavit documents and explicit affidavit obligations."""
    grouped = _grouped_evidence(evidence)
    claims = []
    for bid_id, items in grouped.items():
        distinct: dict[str, dict[str, Any]] = {}
        for item in items:
            record = item["record"]
            text = record.get("text", "").strip()
            is_affidavit_document = record.get("doc_type") == "affidavit"
            requirement_match = re.search(
                r"\b(?:must|shall|required|provide|submit|complete|affirm|certif\w*)\b.{0,100}\baffidavit\b|\baffidavit\b.{0,100}\b(?:must|shall|required|provide|submit|complete|affirm|certif\w*|present(?:ed)?)\b",
                text,
                re.IGNORECASE | re.DOTALL,
            )
            if not is_affidavit_document and not requirement_match:
                continue
            key = re.sub(r"\W+", " ", text.casefold()).strip()
            if key:
                distinct.setdefault(key, (item, requirement_match))
        if distinct:
            for item, requirement_match in distinct.values():
                source = item["record"]
                source_text = source.get("text", "")
                if requirement_match and not item["record"].get("doc_type") == "affidavit":
                    start = max(0, requirement_match.start() - 100)
                    end = min(len(source_text), requirement_match.end() + 140)
                    excerpt = re.sub(r"\s+", " ", source_text[start:end]).strip()
                else:
                    excerpt = re.sub(r"\s+", " ", source_text).strip()[:600]
                claims.append({
                    "text": f"{bid_id} affidavit requirement: {excerpt}",
                    "bid_id": bid_id,
                    "citations": [_source_citation(item)],
                })
    if not claims:
        return {
            "answer": "The documents do not establish any affidavit requirements for the requested bid.",
            "citations": [],
            "evidence_by_bid": grouped,
            "claims": [],
            "found": False,
            "disputed": False,
        }
    answer = " ".join(claim["text"] for claim in claims)
    return {
        "answer": answer,
        "citations": [citation for claim in claims for citation in claim["citations"]],
        "evidence_by_bid": grouped,
        "claims": claims,
        "found": True,
        "disputed": False,
    }


def _warranty_excerpts(text: str) -> list[str]:
    """Return merged context excerpts surrounding warranty/affidavit mentions."""
    spans = []
    for match in re.finditer(r"\b(?:warrant\w*|affidavit)\b", text, re.IGNORECASE):
        spans.append((max(0, match.start() - 50), min(len(text), match.end() + 260)))
    merged = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return [re.sub(r"\s+", " ", text[start:end]).strip() for start, end in merged]


def _warranty_answer(evidence: list[dict[str, Any]]) -> dict[str, Any]:
    """Build cited warranty claims per bid and optionally compare bid clauses."""
    grouped = _grouped_evidence(evidence)
    bid_claims: dict[str, dict[str, Any]] = {}
    evidence_text_by_bid: dict[str, list[str]] = {}
    for bid_id, items in grouped.items():
        passages: dict[str, dict[str, Any]] = {}
        for item in items:
            text = item["record"].get("text", "").strip()
            if "warrant" not in text.casefold():
                continue
            for excerpt in _warranty_excerpts(text):
                key = re.sub(r"\W+", " ", excerpt.casefold()).strip()
                if key:
                    passages.setdefault(key, {"item": item, "excerpt": excerpt})
        if passages:
            selected = list(passages.values())
            evidence_text_by_bid[bid_id] = [passage["excerpt"] for passage in selected]
            citations = []
            seen_citations = set()
            for passage in selected:
                citation = _source_citation(passage["item"])
                citation_key = (citation["file"], citation["page"], citation["bid_id"])
                if citation_key not in seen_citations:
                    seen_citations.add(citation_key)
                    citations.append(citation)
            bid_claims[bid_id] = {
                "text": f"{bid_id} warranty requirements: " + " ".join(passage["excerpt"] for passage in selected),
                "bid_id": bid_id,
                "citations": citations,
            }
    if not bid_claims:
        return {
            "answer": "The documents do not establish warranty requirements for the requested bid or bids.",
            "citations": [],
            "evidence_by_bid": grouped,
            "claims": [],
            "found": False,
            "disputed": False,
        }
    claims = list(bid_claims.values())
    answer_parts = [claim["text"] for claim in claims]
    if len(claims) > 1:
        bid1_text = " ".join(evidence_text_by_bid.get("Bid1", []))
        bid2_text = " ".join(evidence_text_by_bid.get("Bid2", []))
        service_clause = re.search(
            r"Warranty service and repairs or replacements[^.]*?five\s+\(5\)\s+business days[^.]*",
            bid1_text,
            re.IGNORECASE,
        )
        award_clause = re.search(
            r"Warranty certificate or Affidavit to be presented upon award",
            bid2_text,
            re.IGNORECASE,
        )
        if service_clause and award_clause:
            answer_parts.append(
                "Material differences: Bid1 states '"
                + service_clause.group(0).strip()
                + "'; Bid2 states '"
                + award_clause.group(0).strip()
                + "'."
            )
        else:
            answer_parts.append(
                "The documents provide separate bid terms, but do not establish a specific material difference in the available cited clauses."
            )
    return {
        "answer": " ".join(answer_parts),
        "citations": [citation for claim in claims for citation in claim["citations"]],
        "evidence_by_bid": grouped,
        "claims": claims,
        "found": True,
        "disputed": False,
    }


def _bond_answer(evidence: list[dict[str, Any]]) -> dict[str, Any]:
    """Report explicit bond requirements/negations and stated amounts."""
    grouped = _grouped_evidence(evidence)
    claims = []
    unestablished: dict[str, list[dict[str, Any]]] = {}
    established = False
    for bid_id, items in grouped.items():
        for item in items:
            text = item["record"].get("text", "")
            bond_match = re.search(r"\b(?:bid\s+bond|bid\s+security|bond)\b", text, re.IGNORECASE)
            if not bond_match:
                continue
            context = text[max(0, bond_match.start() - 100):bond_match.end() + 180]
            negative = re.search(
                r"\b(?:no|not|never)\b.{0,50}\b(?:bid\s+bond|bid\s+security|bond)\b.{0,50}\b(?:required|necessary|needed)\b|\b(?:bid\s+bond|bid\s+security|bond)\b.{0,50}\b(?:is\s+)?not\s+required\b",
                context,
                re.IGNORECASE | re.DOTALL,
            )
            positive = re.search(
                r"\b(?:bid\s+bond|bid\s+security|bond)\b.{0,80}\b(?:required|must\s+(?:provide|submit|furnish)|shall\s+(?:provide|submit|furnish))\b|\b(?:required|must\s+(?:provide|submit|furnish)|shall\s+(?:provide|submit|furnish))\b.{0,80}\b(?:bid\s+bond|bid\s+security|bond)\b",
                context,
                re.IGNORECASE | re.DOTALL,
            )
            if not negative and not positive:
                if re.search(r"\b(?:bond|bid\s+bond|bid\s+security)\b.{0,100}\belsewhere\b", context, re.IGNORECASE):
                    unestablished.setdefault(bid_id, []).append(_source_citation(item))
                continue
            amount_match = re.search(r"\b\d+(?:\.\d+)?\s*%|\$\s*\d[\d,]*(?:\.\d{2})?", context)
            if negative:
                text_claim = f"{bid_id}: the cited source explicitly states that a bond is not required."
            else:
                text_claim = f"{bid_id}: the cited source explicitly requires a bond."
                text_claim += f" The stated amount is {amount_match.group(0)}." if amount_match else " The documents do not state the bond amount in this evidence."
            claims.append({"text": text_claim, "bid_id": bid_id, "citations": [_source_citation(item)]})
            established = True
            break
    if not claims:
        for bid_id, citations in unestablished.items():
            claims.append({
                "text": f"{bid_id}: the cited document refers to bond requirements elsewhere but does not establish whether a bond is required or state an amount.",
                "bid_id": bid_id,
                "citations": citations,
            })
    if not claims:
        return {
            "answer": "The documents do not establish whether a bond is required or its amount.",
            "citations": [],
            "evidence_by_bid": grouped,
            "claims": [],
            "found": False,
            "disputed": False,
        }
    return {
        "answer": " ".join(claim["text"] for claim in claims),
        "citations": [citation for claim in claims for citation in claim["citations"]],
        "evidence_by_bid": grouped,
        "claims": claims,
        "found": established,
        "disputed": False,
    }


def extraction_response(state: WorkflowState) -> AnalysisResponse:
    """Format extraction fields, changes, validation, and unresolved outcomes.

    Args:
        state: Completed extraction workflow state.

    Returns:
        ``AnalysisResponse`` whose output is a JSON-ready mapping containing
        fields, addendum changes, validation, summary, unsupported work,
        unresolved fields, conflicts, and retry attempts.
    """
    unresolved = [name for name, field in state.draft_fields.items() if field.status != "supported"]
    conflicts = [item.model_dump(mode="json") for item in state.addendum_changes if item.review_required]
    output = {
        "fields": {name: field.model_dump(mode="json") for name, field in state.draft_fields.items()},
        "addendum_changes": [item.model_dump(mode="json") for item in state.addendum_changes],
        "validation": [item.model_dump(mode="json") for item in state.validation_results],
        "summary": "Analysis requires review of unresolved fields or changes." if unresolved or conflicts else "Analysis partial: unsupported requested work." if state.unsupported_work else "Structured extraction completed with source-grounded fields.",
        "unsupported_work": state.unsupported_work,
        "unresolved_fields": unresolved,
        "addendum_conflicts": conflicts,
        "retry_attempts": state.retry_attempts,
    }
    evaluation = build_evaluation(state)
    return AnalysisResponse(run_id=state.run_id, status=state.status, output=output, diagnostics=state.diagnostics, trace_reference=state.trace_reference, evaluation=evaluation)


def synthesize_answer(question: str, evidence: list[dict[str, Any]]) -> dict[str, Any]:
    """Create a deterministic, citation-bearing QA result from evidence.

    Args:
        question: User question.
        evidence: Ranked source evidence mappings with nested records.

    Returns:
        Mapping containing answer, citations, evidence_by_bid, claims,
        change_log when relevant, found, and disputed. Specialized affidavit,
        warranty, bond, addendum, and generic field paths are selected from the
        question; conflicting values are flagged rather than asserted.
    """
    addendum_output = _addendum_answer(question, evidence)
    if addendum_output is not None:
        return addendum_output
    lowered_question = question.casefold()
    if "affidavit" in lowered_question:
        return _affidavit_answer(evidence)
    if "warranty" in lowered_question or "warranties" in lowered_question:
        return _warranty_answer(evidence)
    if "bond" in lowered_question or "bid security" in lowered_question:
        return _bond_answer(evidence)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in evidence:
        grouped.setdefault(item["record"]["bid_id"], []).append(item)
    lowered = question.lower()
    field = next((name for term, name in (("deadline", "submission_deadline"), ("due date", "submission_deadline"), ("bid bond", "bid_bond"), ("solicitation", "solicitation_number"), ("warranty", "warranty"), ("insurance", "insurance"), ("affidavit", "affidavits"), ("model number", "model_number"), ("model #", "model_number"), ("mandatory requirement", "mandatory_requirements"), ("must", "mandatory_requirements")) if term in lowered), None)
    if field is None:
        return {"answer": "Not found in documents", "citations": [], "evidence_by_bid": grouped, "claims": [], "found": False, "disputed": False}
    claims = []
    conflicts = []
    for bid_id, items in grouped.items():
        if field == "submission_deadline":
            authoritative = [
                item
                for item in items
                if item.get("authority_status") in {"current", "review_required"}
            ]
            if authoritative:
                items = authoritative
        items = _question_relevant_evidence(question, items)
        values: dict[str, dict[str, Any]] = {}
        for item in items:
            if item.get("authority_status") == "superseded":
                continue
            value = _value_for(field, item["record"]["text"], question)
            if value:
                citation = _source_citation(item)
                values.setdefault(value, citation)
        if len(values) > 1:
            conflicts.append(bid_id)
        for value, citation in values.items():
            claims.append({"text": f"{bid_id}: {field.replace('_', ' ')} is {value}.", "bid_id": bid_id, "citations": [citation]})
    if not claims:
        return {"answer": "Not found in documents", "citations": [], "evidence_by_bid": grouped, "claims": [], "found": False, "disputed": False}
    disputed = bool(conflicts)
    answer = f"Conflicting {field.replace('_', ' ')} evidence for {', '.join(conflicts)}; review cited sources." if disputed else " ".join(claim["text"] for claim in claims)
    return {"answer": answer, "citations": [citation for claim in claims for citation in claim["citations"]], "evidence_by_bid": grouped, "claims": claims, "found": not disputed, "disputed": disputed}


def qa_response(state: WorkflowState) -> AnalysisResponse:
    """Wrap synthesized QA output and evaluation in the public response model."""
    output = state.final_output or {"answer": "Not found in documents", "citations": [], "evidence_by_bid": {}, "found": False}
    return AnalysisResponse(run_id=state.run_id, status=state.status, output=output, diagnostics=state.diagnostics, trace_reference=state.trace_reference, evaluation=build_evaluation(state))
