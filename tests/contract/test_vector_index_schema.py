import json
from pathlib import Path

from jsonschema import Draft202012Validator


def test_vector_schema_accepts_new_and_legacy_section_metadata():
    schema_path = Path(__file__).parents[1] / "fixtures/schemas/vector-index.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    record = {
        "record_id": "record-1",
        "vector": [0.1, 0.2],
        "scope_id": "Bid1:rfp.pdf",
        "content_fingerprint": "fingerprint",
        "bid_id": "Bid1",
        "source_file": "rfp.pdf",
        "page_number": 1,
        "source_locator": {"relative_path": "rfp.pdf"},
        "text": "Submission deadline",
    }
    validator = Draft202012Validator(schema)

    for section_title in ("Submission", None):
        for content_kind in ("text", "table", "mixed", None):
            candidate = {**record, "section_title": section_title, "content_kind": content_kind}
            assert not list(validator.iter_errors({"records": [candidate]}))

    assert not list(validator.iter_errors({"records": [record]}))