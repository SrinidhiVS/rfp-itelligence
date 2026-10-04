import json
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "tests" / "fixtures" / "schemas" / "processing-report.schema.json"


def test_processing_report_schema_accepts_additive_ingestion_contract() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    report = {
        "bid_id": "Bid1",
        "status": "complete",
        "documents": [
            {
                "document_id": "doc-1",
                "bid_id": "Bid1",
                "file_name": "generic.pdf",
                "relative_path": "Bid1/generic.pdf",
                "detected_format": "pdf",
                "doc_type": "rfp",
                "addendum_number": None,
                "document_date": None,
                "classification": {
                    "doc_type": "rfp",
                    "addendum_number": None,
                    "status": "classified",
                    "evidence": [],
                    "selected_evidence_id": None,
                },
                "status": "parsed",
                "metadata": None,
                "pages": [],
                "diagnostics": [],
            }
        ],
        "pages": [
            {
                "page_id": "page-1",
                "document_id": "doc-1",
                "bid_id": "Bid1",
                "file_name": "generic.pdf",
                "page_number": 1,
                "raw_text": "Item A Value 1",
                "normalized_text": "Item A Value 1",
                "sections": [
                    {
                        "section_id": "section-1",
                        "kind": "paragraph",
                        "text": "Item A Value 1",
                        "heading_path": [],
                        "page_id": "page-1",
                        "source_locator": {"relative_path": "Bid1/generic.pdf", "page_number": 1},
                    }
                ],
                "classification": None,
                "metadata": None,
                "status": "parsed",
                "tables": [],
                "diagnostics": [],
            }
        ],
        "tables": [
            {
                "table_id": "table-1",
                "page_id": "page-1",
                "title": None,
                "has_header": False,
                "columns": [None, None],
                "rows": [["Item A", "Value 1"]],
                "source_bounds": None,
                "status": "parsed",
                "diagnostics": [],
            }
        ],
        "chunks": [
            {
                "chunk_id": "chunk-1",
                "bid_id": "Bid1",
                "document_id": "doc-1",
                "page_id": "page-1",
                "chunk_index": 0,
                "section_title": None,
                "text": "Item A Value 1",
                "content_kind": "text",
                "source_file": "generic.pdf",
                "file_name": "generic.pdf",
                "page_number": 1,
                "source_locator": {"relative_path": "Bid1/generic.pdf"},
                "diagnostic_ids": [],
                "doc_type": "rfp",
                "addendum_number": None,
                "document_date": None,
            }
        ],
        "diagnostics": [],
        "retention_report": {
            "corpus_name": "fixture",
            "manifest_version": "1.0",
            "text": {"expected": 1, "retained": 1, "missing": 0, "uncertain": 0, "coverage": 1.0},
            "tables": {"expected": 1, "retained": 1, "missing": 0, "uncertain": 0, "coverage": 1.0},
            "items": [],
        },
    }

    Draft202012Validator(schema).validate(report)
    chunk = report["chunks"][0]
    assert chunk["source_file"] == "generic.pdf"
    assert chunk["file_name"] == "generic.pdf"
    assert report["tables"][0]["rows"][0] == ["Item A", "Value 1"]
