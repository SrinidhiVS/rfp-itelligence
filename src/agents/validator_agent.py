"""Validate workflow fields for format, source support, and consistency."""

from __future__ import annotations

from datetime import datetime
import re

from .extraction_agent import _DATE_PATTERN
from .state import Diagnostic, ExtractionField, ValidationResult


def _valid_format(name: str, value: object) -> bool:
    """Validate non-empty strings and field-specific deadline/bond formats."""
    text = str(value).strip()
    if name == "submission_deadline":
        for date_format in ("%Y-%m-%d", "%B %d, %Y", "%B %d %Y"):
            try:
                datetime.strptime(text, date_format)
                return True
            except ValueError:
                continue
        return False
    if name == "bid_bond":
        match = re.match(r"^(\d+(?:\.\d+)?)\s*%(?:\s+of\s+.+)?$", text, re.IGNORECASE)
        return bool(match and 0 <= float(match.group(1)) <= 100)
    return bool(text)


def _supported_by_source(field: ExtractionField, evidence: list[dict]) -> bool:
    """Verify a field value appears in a cited record from the evidence list."""
    for item in evidence:
        record = item["record"]
        if not any(citation.file == record.get("source_file") and citation.bid_id == record.get("bid_id") and citation.page == record.get("page_number") for citation in field.citations):
            continue
        text = record.get("text", "")
        if str(field.value).lower() in text.lower():
            return True
        if field.name == "submission_deadline":
            for match in _DATE_PATTERN.finditer(text):
                for date_format in ("%Y-%m-%d", "%B %d, %Y", "%B %d %Y"):
                    try:
                        if datetime.strptime(str(field.value), "%Y-%m-%d").date() == datetime.strptime(match.group(), date_format).date():
                            return True
                    except ValueError:
                        continue
    return False


def validate_fields(fields: dict[str, ExtractionField], evidence: list[dict] | None = None) -> tuple[list[ValidationResult], list[Diagnostic]]:
    """Validate every field and emit per-field results and diagnostics.

    Args:
        fields: Extracted field mapping to assess.
        evidence: Optional source records used to confirm citation support.

    Returns:
        Tuple of ``ValidationResult`` and ``Diagnostic`` lists. Results carry
        format, support, consistency, citation-completeness, rejection, and
        retry-eligibility flags; valid not_found fields are accepted.
    """
    results: list[ValidationResult] = []
    diagnostics: list[Diagnostic] = []
    for name, field in fields.items():
        has_value = field.value is not None
        format_valid = _valid_format(name, field.value) if has_value else True
        evidence_supported = has_value and bool(field.citations) and (evidence is None or _supported_by_source(field, evidence))
        consistency_valid = not (name == "bid_bond" and field.value is not None and "no bond required" in str(fields.get("mandatory_requirements", ExtractionField(name="mandatory_requirements")).value).lower())
        supported = has_value and evidence_supported and format_valid and consistency_valid and field.status == "supported"
        accepted_missing = field.status == "not_found" and not has_value
        status = "passed" if supported or accepted_missing else "review_required" if field.status == "review_required" else "rejected"
        reason = None if status == "passed" else "invalid field value or unit" if not format_valid else "cited evidence does not support the value" if not evidence_supported else "field conflicts with another requirement" if not consistency_valid else field.notes or "field failed validation"
        result = ValidationResult(
            scope="field", field=name, status=status,
            evidence_supported=evidence_supported, citation_complete=bool(field.citations) if has_value else True,
            format_valid=format_valid, consistency_valid=consistency_valid,
            unsupported_claim=has_value and not evidence_supported,
            rejection_reason=reason,
            retry_eligible=status == "rejected",
        )
        results.append(result)
        if result.status != "passed":
            diagnostics.append(Diagnostic(code="field_rejected" if result.status == "rejected" else "field_review", message=reason or "field failed validation", severity="warning", field=name, retryable=result.retry_eligible))
    return results, diagnostics
