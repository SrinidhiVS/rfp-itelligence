"""Reconcile competing field values found across an RFP and its addenda.

The module orders evidence by addendum number and page, selects the latest
encountered value, and records replacements or unresolved conflicts as
``AddendumChange`` objects. Evidence without an addendum number is treated as
requiring review when it changes an already selected value.
"""

from __future__ import annotations

from .models import AddendumChange, RankedEvidence


def reconcile(values: list[tuple[int | None, int, str, RankedEvidence]], field: str) -> tuple[str | None, list[AddendumChange]]:
    """Select the controlling value and describe changes found in the evidence.

    Args:
        values: Evidence entries shaped as ``(addendum_number, page_number,
            value, ranked_evidence)``. ``addendum_number`` may be ``None``;
            ``page_number`` is used to order entries within an addendum.
        field: Name of the bid field whose values are being reconciled.

    Returns:
        A pair ``(current_value, changes)``. ``current_value`` is the final
        string value, or ``None`` when ``values`` is empty. ``changes`` is an
        ordered list of ``AddendumChange`` records; each citation contains the
        evidence source file and page. Conflicting values at the same numbered
        addendum, or changes from unnumbered evidence, are marked for review.
    """
    ordered = sorted(values, key=lambda item: (item[0] is None, item[0] or 10**9, item[1]))
    changes: list[AddendumChange] = []
    current: str | None = None
    current_number: int | None = None
    for number, page, value, evidence in ordered:
        if current is None:
            current = value
            current_number = number
            continue
        review = number is None
        if value != current:
            same_addendum_conflict = number is not None and number == current_number
            changes.append(AddendumChange(
                field,
                current,
                value,
                number,
                [{"file": evidence.record.source_file, "page": evidence.record.page_number}],
                "conflict" if same_addendum_conflict or review else "replacement",
                review,
            ))
            current = value
            current_number = number
    return current, changes
