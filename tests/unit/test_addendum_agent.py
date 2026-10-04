from src.agents.addendum_agent import reconcile_changes
from src.agents.state import ExtractionField


def test_addendum_reconciliation_emits_cited_change():
    fields = {"submission_deadline": ExtractionField(name="submission_deadline", value="old", status="supported", citations=[{"file": "rfp", "bid_id": "Bid1"}])}
    evidence = [{"record": {"source_file": "addendum.html", "page_number": 1, "bid_id": "Bid1", "source_locator": {}, "doc_type": "addendum", "addendum_number": 2, "text": "submission deadline revised to October 10, 2026"}, "authority_status": "current"}]
    changes = reconcile_changes(fields, evidence)
    assert changes[0].addendum_number == 2
    assert changes[0].citations
    assert fields["submission_deadline"].value == "October 10, 2026"


def test_addenda_only_change_relevant_fields_in_latest_valid_order():
    fields = {"submission_deadline": ExtractionField(name="submission_deadline", value="2026-09-01", status="supported", citations=[{"file": "rfp.pdf", "bid_id": "Bid1"}]),
              "warranty": ExtractionField(name="warranty", value="2 years", status="supported", citations=[{"file": "rfp.pdf", "bid_id": "Bid1"}])}

    def addendum(number, text):
        return {"record": {"source_file": f"addendum-{number}.pdf", "page_number": 1, "bid_id": "Bid1", "source_locator": {}, "doc_type": "addendum", "addendum_number": number, "text": text}, "authority_status": "current"}

    evidence = [addendum(3, "New delivery address only"), addendum(2, "submission deadline revised to 2026-11-20"), addendum(1, "submission deadline revised to 2026-10-10"), addendum(4, "submission deadline revised to 2026-99-99")]
    changes = reconcile_changes(fields, evidence)
    assert fields["submission_deadline"].value == "2026-11-20"
    assert fields["warranty"].value == "2 years"
    assert changes[0].addendum_number == 2
    assert {change.field for change in changes} == {"submission_deadline"}


def test_conflicting_or_unordered_addenda_require_review():
    def deadline():
        return {"submission_deadline": ExtractionField(name="submission_deadline", value="2026-09-01", status="supported", citations=[{"file": "rfp.pdf", "bid_id": "Bid1"}])}

    def addendum(number, text):
        return {"record": {"source_file": "addendum.pdf", "page_number": 1, "bid_id": "Bid1", "source_locator": {}, "doc_type": "addendum", "addendum_number": number, "text": text}}

    conflicting = deadline()
    changes = reconcile_changes(conflicting, [addendum(2, "deadline changed to 2026-11-20"), addendum(2, "deadline changed to 2026-11-21")])
    assert conflicting["submission_deadline"].value == "2026-09-01"
    assert changes and changes[0].review_required
    unordered = deadline()
    changes = reconcile_changes(unordered, [addendum(None, "deadline changed to 2026-12-01")])
    assert unordered["submission_deadline"].value == "2026-09-01"
    assert changes and changes[0].review_required
