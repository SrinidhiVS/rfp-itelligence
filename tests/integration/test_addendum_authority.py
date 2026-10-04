from src.agents.addendum_agent import reconcile_changes
from src.agents.state import ExtractionField


def test_authoritative_addendum_replaces_base_value_and_cites_controller():
    fields = {"submission_deadline": ExtractionField(name="submission_deadline", value="old deadline", status="supported", citations=[{"file": "base.html", "bid_id": "Bid1"}])}
    evidence = [{"record": {"source_file": "addendum-2.html", "page_number": 2, "bid_id": "Bid1", "source_locator": {}, "doc_type": "addendum", "addendum_number": 2, "text": "submission deadline revised to October 20"}, "authority_status": "current", "superseded_by": None}]
    changes = reconcile_changes(fields, evidence)
    assert "October 20" in fields["submission_deadline"].value
    assert fields["submission_deadline"].citations[0].file == "addendum-2.html"
    assert changes[0].previous_value == "old deadline"
