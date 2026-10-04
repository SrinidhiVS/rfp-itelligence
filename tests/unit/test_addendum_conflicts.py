from src.search.addendum import reconcile
from src.search.models import IndexRecord, RankedEvidence


def evidence(number, page, text):
    record = IndexRecord(text, text, "scope", "fp", text, "Bid1", "addendum.pdf", page, None, "addendum", number, None, {}, [])
    return RankedEvidence(text, 1, 1.0, record, ["keyword"], "complete")


def test_same_addendum_conflict_is_logged() -> None:
    value, changes = reconcile([(1, 1, "A", evidence(1, 1, "A")), (1, 2, "B", evidence(1, 2, "B"))], "deadline")
    assert value == "B"
    assert changes[0].reason == "conflict"
    assert changes[0].review_required is False


def test_missing_addendum_number_requires_review() -> None:
    _, changes = reconcile([(None, 1, "A", evidence(None, 1, "A")), (2, 1, "B", evidence(2, 1, "B"))], "deadline")
    assert changes
    assert changes[-1].review_required is True
