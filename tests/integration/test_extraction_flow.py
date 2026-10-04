import json
from pathlib import Path

from src.frontend.views import extraction_view


def test_extraction_response_fixture_renders_field_metadata():
    payload = json.loads(Path("tests/fixtures/frontend/extraction-response.json").read_text(encoding="utf-8"))
    view = extraction_view(payload)
    field = view["fields"]["Due Date"]
    assert field["value"] == "October 20"
    assert field["confidence"] == 0.9
    assert field["citations"][0]["file"] == "addendum.pdf"
