import json
from pathlib import Path

from src.frontend.views import answer_view


def test_question_response_fixture_renders_citations_and_bid_groups():
    payload = json.loads(Path("tests/fixtures/frontend/qa-response.json").read_text(encoding="utf-8"))
    view = answer_view(payload)
    assert view["found"] is True
    assert view["citations"][0]["Bid"] == "Bid1"
    assert "Bid1" in view["evidence_by_bid"]
