"""Extract workflow fields from evidence and verify model proposals locally."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from .state import Citation, ExtractionField
from src.field_registry import AGENT_FIELD_ALIASES

FIELD_TERMS = AGENT_FIELD_ALIASES


def _citation(item: dict[str, Any]) -> Citation:
    """Convert nested ranked evidence into an agent citation model."""
    record = item["record"]
    return Citation(
        file=record["source_file"], page=record.get("page_number"), bid_id=record["bid_id"],
        locator=record.get("source_locator", {}), authority_status=item.get("authority_status"),
        superseded_by=item.get("superseded_by"),
    )


def extract_fields(evidence: list[dict[str, Any]], field_names: list[str], model_values: dict[str, Any] | None = None, *, goal: str | None = None) -> dict[str, ExtractionField]:
    """Build one cited disposition for each requested agent field.

    Args:
        evidence: Ranked evidence mappings with nested source records.
        field_names: Requested field keys from the plan.
        model_values: Optional provider proposals keyed by field name.
        goal: Optional request context used to select mandatory requirement text.

    Returns:
        Mapping from requested field to ``ExtractionField``. Each is supported,
        not_found, or review_required; model proposals are retained only when
        the value is present in or equivalent to the cited passage.
    """
    model_values = model_values or {}
    fields: dict[str, ExtractionField] = {}
    for name in field_names:
        terms = FIELD_TERMS.get(name, (name.replace("_", " "),))
        matches = [item for item in evidence if any(term in item["record"]["text"].lower() for term in terms)]
        if not matches:
            fields[name] = ExtractionField(name=name, status="not_found", notes="Not found in documents")
            continue
        selected = next(((item, value) for item in matches if (value := _value_for(name, item["record"]["text"], goal))), None)
        if selected is None:
            fields[name] = ExtractionField(name=name, status="review_required", notes="No field-specific value supported by retrieved evidence")
            continue
        item, value = selected
        proposal = model_values.get(name)
        if proposal is not None and not _supported_value(name, str(proposal), item["record"]["text"], value):
            fields[name] = ExtractionField(name=name, status="review_required", citations=[_citation(item)], notes="Proposed value is not supported by the cited passage")
            continue
        fields[name] = ExtractionField(name=name, value=proposal if proposal is not None else value, confidence=0.8, citations=[_citation(item)], status="supported")
    return fields


_MONTH_PATTERN = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
_DATE_PATTERN = re.compile(rf"\b\d{{4}}-\d{{2}}-\d{{2}}\b|\b{_MONTH_PATTERN} \d{{1,2}},? \d{{4}}\b", re.IGNORECASE)
_PARTIAL_DATE_PATTERN = re.compile(rf"\b{_MONTH_PATTERN} \d{{1,2}}\b", re.IGNORECASE)


def _value_for(name: str, text: str, context: str | None = None) -> str | None:
    """Extract a locally supported value for a planned agent field."""
    if name == "submission_deadline":
        for match in re.finditer(r"\b(?:submission deadline|deadline|due date|submit by)\b", text, re.IGNORECASE):
            following = text[match.end():match.end() + 100]
            date = _DATE_PATTERN.search(following) or _PARTIAL_DATE_PATTERN.search(following)
            if date:
                return date.group()
        return None
    if name == "solicitation_number":
        match = re.search(r"\b(?:solicitation|bid|rfp)\s*(?:number|no\.?|#)?\s*[:#]?\s*([A-Z]{1,8}[-_]\d{3,}|\d{3,})\b", text, re.IGNORECASE)
        return match.group(1) if match else None
    if name == "model_number":
        match = re.search(r"\bSI#\s+[A-Z0-9-]+\s+((?:[A-Z][\w-]*\s+){1,3}\d{3,5})\b", text, re.IGNORECASE)
        return " ".join(match.group(1).split()) if match else None
    if name == "bid_bond":
        match = re.search(r"\bbid (?:bond|security)\b\s*(?::|is|of)?\s*(\d+(?:\.\d+)?\s*%\s*(?:of\s+[^.\n]+)?)", text, re.IGNORECASE)
        return match.group(1).strip() if match else None
    if name == "mandatory_requirements" and context:
        stop_words = {"a", "an", "and", "are", "applies", "for", "from", "how", "is", "it", "of", "on", "or", "the", "to", "what", "with", "mandatory", "requirement", "requirements", "must", "extract"}
        terms = {term[:-1] if len(term) > 4 and term.endswith("s") else term for term in re.findall(r"[a-z0-9]+", context.lower()) if term not in stop_words}
        if terms:
            normalized = re.sub(r"\s+", " ", text).strip()
            clauses = [clause.strip() for clause in re.split(r"(?<=[.!?])\s+", normalized) if re.search(r"\b(?:must|required|mandatory)\b", clause, re.IGNORECASE)]
            scored = [(len(terms & {term[:-1] if len(term) > 4 and term.endswith("s") else term for term in re.findall(r"[a-z0-9]+", clause.lower())}), clause) for clause in clauses]
            best_score = max((score for score, _ in scored), default=0)
            best_values = {value for score, value in scored if score == best_score and score > 0}
            if len(best_values) == 1:
                return next(iter(best_values))
            return None
    lines = [line.strip() for line in re.split(r"[\n\r]+", text) if line.strip()]
    for line in lines:
        if any(term in line.lower() for term in FIELD_TERMS.get(name, (name.replace("_", " "),))):
            value = line.split(":", 1)[-1].strip() if ":" in line else line
            if value.lower() not in FIELD_TERMS.get(name, ()):
                return value[:200]
    return None


def _supported_value(name: str, proposed: str, text: str, extracted: str) -> bool:
    """Check a provider proposal against source text and extracted value."""
    if proposed.lower() in text.lower() or proposed == extracted:
        return True
    if name == "submission_deadline":
        for date_format in ("%B %d, %Y", "%B %d %Y", "%Y-%m-%d"):
            try:
                if datetime.strptime(proposed, "%Y-%m-%d").date() == datetime.strptime(extracted, date_format).date():
                    return True
            except ValueError:
                continue
    return False
