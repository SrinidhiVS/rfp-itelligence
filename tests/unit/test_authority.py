from src.search.authority import apply_requirement_authority
from src.search.models import IndexRecord, RankedEvidence


def evidence(record_id, text, doc_type, page, addendum=None):
    record = IndexRecord(record_id, record_id, f"Bid1:{record_id}", "fp", text, "Bid1", f"{record_id}.pdf", page, None, doc_type, addendum, None, {}, [])
    return RankedEvidence(record_id, 1, 0.5, record, ["keyword"], "complete")


def test_authority_is_requirement_level() -> None:
    original = evidence("original", "Solicitation Due 27-JUN-2024 14:00:00", "rfp", 32)
    amendment = evidence("amendment", "The new due date for this RFP will be July 9, 2024 at 2:00 PM CST.", "addendum", 1, 2)
    results = apply_requirement_authority([original, amendment], "final submission deadline")
    assert next(item for item in results if item.record.record_id == "amendment").authority_status == "current"
    old = next(item for item in results if item.record.record_id == "original")
    assert old.authority_status == "superseded"
    assert old.superseded_by == "amendment"
    assert old.record.status == "current"


def test_unrelated_addendum_is_not_authoritative() -> None:
    result = evidence("warranty", "This addendum clarifies warranty coverage.", "addendum", 1, 3)
    assert apply_requirement_authority([result], "final submission deadline")[0].authority_status == "supporting"
