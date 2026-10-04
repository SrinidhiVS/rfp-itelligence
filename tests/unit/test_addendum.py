from pathlib import Path

from src.search.addendum import reconcile
from src.search.models import IndexRecord, RankedEvidence


def evidence(number: int, page: int, text: str) -> RankedEvidence:
    record = IndexRecord(text, text, "scope", "fp", text, "Bid1", f"Addendum {number}.pdf", page, None, "addendum", number, None, {}, [])
    return RankedEvidence(text, 1, 1.0, record, ["keyword"], "complete")


def test_addendum_reconcile_applies_numeric_order() -> None:
    value, changes = reconcile([(2, 1, "new", evidence(2, 1, "new")), (1, 1, "old", evidence(1, 1, "old"))], "deadline")
    assert value == "new"
    assert changes[0].previous_value == "old"
