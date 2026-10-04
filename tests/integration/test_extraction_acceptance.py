import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from src.agents.graph import AnalysisWorkflow
from src.agents.retrieval_agent import RetrievalAgent
from src.api import app as app_module
from src.extraction.cli import main as extraction_cli_main
from src.extraction.extractor import StructuredExtractor
from src.extraction.fields import CANONICAL_FIELDS
from src.extraction.serialization import read_record
from src.ingestion.pipeline import IngestionPipeline
from src.search.config import index_path
from src.search.storage import CorpusStore


def test_empty_bid_still_produces_valid_twenty_field_record():
    record = StructuredExtractor().extract("Bid1", [])
    assert tuple(record.fields) == CANONICAL_FIELDS
    assert record.validation.not_found == 20
    assert record.model_dump_json()


def _source_evidence(item, bid_id):
    return {
        "record": {
            "source_file": item["file"],
            "page_number": item.get("page"),
            "source_locator": item.get("location") or f"page {item.get('page')}",
            "bid_id": bid_id,
            "doc_type": item.get("type", "rfp"),
            "content_kind": item.get("content_kind"),
            "addendum_number": item.get("addendum_number"),
            "document_date": item.get("document_date"),
            "text": item["text"],
        },
        "authority_status": item.get("authority_status"),
    }


def _citation_keys(citations):
    keys = set()
    for citation in citations:
        get = (lambda name, default=None: citation.get(name, default)) if isinstance(citation, dict) else (lambda name, default=None: getattr(citation, name, default))
        file = get("file")
        keys.add((file, get("page")))
        location = get("location")
        if not isinstance(location, dict):
            continue
        keys.update((file, page) for page in location.get("page_numbers", []))
        keys.update(
            (file, segment.get("page_number"))
            for segment in location.get("source_segments", [])
            if segment.get("page_number") is not None
        )
    return keys


def _expected_citation_keys(citations):
    assert all(citation.get("location") or citation.get("page") for citation in citations)
    return {(citation["file"], citation.get("page")) for citation in citations}


def _citations_are_locatable(citations):
    for citation in citations:
        get = (lambda name: citation.get(name)) if isinstance(citation, dict) else (lambda name: getattr(citation, name, None))
        if not get("file") or (get("page") is None and not get("location")) or not get("excerpt"):
            return False
    return bool(citations)


def _matrix_outcome(case, name, field):
    if name in case["not_found"]:
        expected_status = "not_found"
        expected = None
    elif name in case.get("review_required", {}):
        expected_status = "review_required"
        expected = case["review_required"][name]
    else:
        expected_status = "supported"
        expected = case["supported"][name]

    if field.status != expected_status:
        matches = False
    elif expected_status != "supported":
        matches = field.value is None
    elif "items" in expected:
        expected_values = [item["value"] if isinstance(item, dict) else item for item in expected["items"]]
        actual_items = field.value or []
        actual_values = [item.value if hasattr(item, "value") else item.get("value") for item in actual_items]
        matches = sorted(str(value).casefold() for value in actual_values) == sorted(str(value).casefold() for value in expected_values)
        expected_by_value = {str(value).casefold(): item for value, item in zip(expected_values, expected["items"])}
        for actual in actual_items:
            actual_value = actual.value if hasattr(actual, "value") else actual.get("value")
            actual_attributes = actual.attributes if hasattr(actual, "attributes") else actual.get("attributes", {})
            wanted = expected_by_value.get(str(actual_value).casefold())
            if isinstance(wanted, dict) and actual_attributes != wanted.get("attributes", {}):
                matches = False
    else:
        matches = field.value == expected["value"]

    expected_value = None
    reason = None
    if expected_status == "supported":
        expected_value = expected.get("value", [item.get("value") if isinstance(item, dict) else item for item in expected.get("items", [])])
    elif expected_status == "not_found":
        reason = case.get("reasons", {}).get(name)
    else:
        reason = case.get("reasons", {}).get(name)
        expected_value = expected.get("value")

    actual_value = field.model_dump(mode="json")["value"]
    citations_complete = (
        field.status == "supported"
        and matches
        and _citations_are_locatable(field.citations)
        and (
            not isinstance(field.value, list)
            or all(
                _citations_are_locatable(item.citations if hasattr(item, "citations") else item.get("citations", []))
                for item in field.value
            )
        )
    )
    return {
        "field": name,
        "expected_status": expected_status,
        "actual_status": field.status,
        "expected_value": expected_value,
        "actual_value": actual_value,
        "outcome": expected_status if matches else "incorrect",
        "citation_complete": citations_complete,
        "reason": reason if matches else "Actual status or value differs from the adjudicated matrix.",
    }


def test_value_level_matrix_covers_all_fields_across_bid1_bid2_and_unseen_bid():
    fixture = json.loads(Path("tests/fixtures/structured_extraction/value-level-acceptance.json").read_text(encoding="utf-8"))
    for bid_id, case in fixture["bids"].items():
        record = StructuredExtractor().extract(bid_id, [_source_evidence(item, bid_id) for item in case["evidence"]])
        expected_fields = case["supported"]
        not_found = set(case["not_found"])
        review_required = set(case.get("review_required", {}))
        assert set(expected_fields) | not_found | review_required == set(CANONICAL_FIELDS)
        assert set(expected_fields).isdisjoint(not_found)
        assert set(expected_fields).isdisjoint(review_required)
        assert not_found.isdisjoint(review_required)
        assert tuple(record.fields) == CANONICAL_FIELDS
        for name in CANONICAL_FIELDS:
            field = record.fields[name]
            if name in not_found:
                assert field.status == "not_found", (bid_id, name, field)
                assert field.value is None
                assert field.citations == []
                assert field.confidence == 0.0
                if bid_id in {"Bid1", "Bid2"}:
                    assert case["reasons"][name].strip()
                    assert name.casefold() in field.notes.casefold(), (bid_id, name, field.notes)
                    assert "verify source coverage" in field.notes.casefold(), (bid_id, name, field.notes)
                assert field.notes.strip()
                continue
            if name in review_required:
                expected = case["review_required"][name]
                assert field.status == "review_required", (bid_id, name, field)
                assert field.value is None
                assert field.confidence == 0.0
                assert case["reasons"][name].strip()
                assert _expected_citation_keys(expected["citations"]) <= _citation_keys(field.citations)
                continue
            expected = expected_fields[name]
            assert field.status == "supported", (bid_id, name, field)
            assert field.value is not None
            assert field.confidence > 0.0
            if name == "Product Specification":
                actual_items = [item.value for item in field.value]
                actual_text = " ".join(actual_items).casefold()
                expected_items = expected["items"]
                for item in expected_items:
                    expected_value = item["value"] if isinstance(item, dict) else item
                    assert str(expected_value).casefold() in actual_text, (bid_id, name, expected_value)
                expected_citations = [
                    citation
                    for item in expected_items if isinstance(item, dict)
                    for citation in item.get("citations", [])
                ]
                assert _expected_citation_keys(expected_citations) <= _citation_keys(field.citations), (bid_id, name)
                assert _citations_are_locatable(field.citations), (bid_id, name)
                continue
            if "items" in expected:
                expected_items = expected["items"]
                expected_values = [item["value"] if isinstance(item, dict) else item for item in expected_items]
                actual_values = [item.value for item in field.value]
                assert sorted(str(value).casefold() for value in actual_values) == sorted(str(value).casefold() for value in expected_values), (bid_id, name)
                wanted_by_value = {
                    str(item["value"] if isinstance(item, dict) else item).casefold(): item
                    for item in expected_items
                }
                for actual in field.value:
                    actual_value = actual.value if hasattr(actual, "value") else actual.get("value")
                    wanted = wanted_by_value[str(actual_value).casefold()]
                    if isinstance(wanted, dict):
                        assert actual.attributes == wanted.get("attributes", {}), (bid_id, name, actual)
                        citations = wanted.get("citations", expected.get("citations", []))
                    else:
                        citations = expected.get("citations", [])
                    assert _expected_citation_keys(citations) <= _citation_keys(actual.citations)
                expected_citations = expected.get("citations") or [
                    source for item in expected_items if isinstance(item, dict) for source in item.get("citations", [])
                ]
            else:
                assert field.value == expected["value"], (bid_id, name, field.value)
                expected_citations = expected["citations"]
            assert _expected_citation_keys(expected_citations) <= _citation_keys(field.citations), (bid_id, name)
            assert _citations_are_locatable(field.citations), (bid_id, name)


def test_bid_addendum_change_logs_match_adjudicated_source_history():
    fixture = json.loads(Path("tests/fixtures/structured_extraction/value-level-acceptance.json").read_text(encoding="utf-8"))
    for bid_id in ("Bid1", "Bid2"):
        case = fixture["bids"][bid_id]
        record = StructuredExtractor().extract(bid_id, [_source_evidence(item, bid_id) for item in case["evidence"]])
        expected_changes = case.get("expected_addendum_changes", [])
        actual_changes = {change.field: change for change in record.addendum_changes}
        for expected in expected_changes:
            actual = actual_changes[expected["field"]]
            assert actual.field == expected["field"]
            assert actual.previous_value == expected["previous_value"]
            assert actual.current_value == expected["current_value"]
            assert _citation_keys(actual.previous_citations) == _expected_citation_keys(expected["previous_citations"])
            assert _citation_keys(actual.current_citations) == _expected_citation_keys(expected["current_citations"])
            assert (actual.controlling_citation.file, actual.controlling_citation.page) == (
                expected["controlling_citation"]["file"], expected["controlling_citation"].get("page")
            )
            assert actual.addendum_number == expected["addendum_number"]
            assert actual.review_required is expected["review_required"]


def test_cli_and_api_records_match_adjudicated_bid_matrix(tmp_path, monkeypatch):
    fixture = json.loads(Path("tests/fixtures/structured_extraction/value-level-acceptance.json").read_text(encoding="utf-8"))
    indexed_records = CorpusStore(index_path()).load().records

    class IndexedCorpusWorkflow:
        def invoke(self, state):
            bid_id = state.bid_ids[0]
            state.status = "completed"
            state.retrieved_evidence = [
                {"record": record.__dict__, "authority_status": record.status}
                for record in indexed_records
                if record.bid_id == bid_id
            ]
            return state

    monkeypatch.setattr(app_module, "workflow", IndexedCorpusWorkflow())
    client = TestClient(app_module.app)
    report_bids = {}
    for bid_id in ("Bid1", "Bid2"):
        output_directory = tmp_path / "cli"
        assert extraction_cli_main(["extract", "--input", bid_id, "--output", str(output_directory)]) == 0
        cli_record = read_record(output_directory / bid_id / "structured-record.json")
        assert cli_record.bid_id == bid_id

        response = client.post("/v1/analysis/extract", json={"mode": "extraction", "bid_id": bid_id, "trace": False})
        assert response.status_code == 200
        api_fields = response.json()["output"]["fields"]
        cli_fields = {name: field.model_dump(mode="json") for name, field in cli_record.fields.items()}
        assert api_fields == cli_fields

        case = fixture["bids"][bid_id]
        assert tuple(cli_record.fields) == CANONICAL_FIELDS
        for name in CANONICAL_FIELDS:
            field = cli_record.fields[name]
            if name in case["not_found"]:
                assert field.status == "not_found" and field.value is None, (bid_id, name, field)
                assert case["reasons"][name].strip()
                assert name.casefold() in field.notes.casefold(), (bid_id, name, field.notes)
                assert "verify source coverage" in field.notes.casefold(), (bid_id, name, field.notes)
                continue
            expected = case["supported"][name]
            assert field.status == "supported", (bid_id, name, field)
            if name == "Product Specification":
                actual_by_value = {
                    str(item.get("value") if isinstance(item, dict) else item.value).casefold(): item
                    for item in field.value
                }
                expected_values = [item["value"] if isinstance(item, dict) else item for item in expected["items"]]
                actual_values = [item.get("value") if isinstance(item, dict) else item.value for item in field.value]
                assert sorted(str(value).casefold() for value in actual_values) == sorted(str(value).casefold() for value in expected_values), (bid_id, name)
                for expected_item in expected["items"]:
                    expected_value = expected_item["value"] if isinstance(expected_item, dict) else expected_item
                    actual = actual_by_value[str(expected_value).casefold()]
                    if isinstance(expected_item, dict):
                        actual_citations = actual.get("citations", []) if isinstance(actual, dict) else actual.citations
                        assert _expected_citation_keys(expected_item.get("citations", [])) <= _citation_keys(actual_citations), (bid_id, name, expected_value)
            elif "items" in expected:
                expected_items = expected["items"]
                expected_values = [item["value"] if isinstance(item, dict) else item for item in expected_items]
                actual_values = [item.get("value") if isinstance(item, dict) else item.value for item in field.value]
                assert sorted(str(value).casefold() for value in actual_values) == sorted(str(value).casefold() for value in expected_values), (bid_id, name)
                wanted_by_value = {
                    str(item["value"] if isinstance(item, dict) else item).casefold(): item
                    for item in expected_items
                }
                for actual in field.value:
                    actual_value = actual.get("value") if isinstance(actual, dict) else actual.value
                    attributes = actual.get("attributes", {}) if isinstance(actual, dict) else actual.attributes
                    actual_citations = actual.get("citations", []) if isinstance(actual, dict) else actual.citations
                    wanted = wanted_by_value[str(actual_value).casefold()]
                    if isinstance(wanted, dict):
                        assert attributes == wanted.get("attributes", {}), (bid_id, name, actual_value)
                        citations = wanted.get("citations", expected.get("citations", []))
                    else:
                        citations = expected.get("citations", [])
                    assert _expected_citation_keys(citations) <= _citation_keys(actual_citations)
                    if name == "Product" and isinstance(wanted, dict):
                        assert _expected_citation_keys(wanted.get("citations", [])) <= _citation_keys(actual_citations), (bid_id, name, actual_value)
            else:
                assert field.value == expected["value"], (bid_id, name, field.value)
                assert _expected_citation_keys(expected["citations"]) <= _citation_keys(field.citations)

            assert field.citations, (bid_id, name)
            assert all(
                citation.file and (citation.page is not None or citation.location) and citation.excerpt
                and citation.bid_id == bid_id
                for citation in field.citations
            ), (bid_id, name)

        actual_changes = {change.field: change for change in cli_record.addendum_changes}
        for expected_change in case.get("expected_addendum_changes", []):
            actual_change = actual_changes[expected_change["field"]]
            assert actual_change.previous_value == expected_change["previous_value"]
            assert actual_change.current_value == expected_change["current_value"]
            assert _citation_keys(actual_change.previous_citations) == _expected_citation_keys(expected_change["previous_citations"])
            assert _citation_keys(actual_change.current_citations) == _expected_citation_keys(expected_change["current_citations"])
            assert (actual_change.controlling_citation.file, actual_change.controlling_citation.page) == (
                expected_change["controlling_citation"]["file"], expected_change["controlling_citation"].get("page")
            )
            assert actual_change.addendum_number == expected_change["addendum_number"]
            assert actual_change.review_required is expected_change["review_required"]

        results = [_matrix_outcome(case, name, cli_record.fields[name]) for name in CANONICAL_FIELDS]
        counts = {
            outcome: sum(result["outcome"] == outcome for result in results)
            for outcome in ("supported", "not_found", "review_required", "incorrect")
        }
        counts["citation_complete"] = sum(result["citation_complete"] for result in results)
        assert len(results) == 20
        assert sum(counts[outcome] for outcome in ("supported", "not_found", "review_required", "incorrect")) == 20
        report_bids[bid_id] = {"fields": results, "counts": counts}

    report = {
        "schema_version": 1,
        "source_matrix": "tests/fixtures/structured_extraction/value-level-acceptance.json",
        "bids": report_bids,
    }
    report_path = Path("output/extraction-accuracy/accuracy-report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    persisted_report = json.loads(report_path.read_text(encoding="utf-8"))
    assert set(persisted_report["bids"]) == {"Bid1", "Bid2"}
    assert all(len(result["fields"]) == 20 for result in persisted_report["bids"].values())
    assert all(result["counts"]["incorrect"] == 0 for result in persisted_report["bids"].values())


def test_value_matrix_covers_missing_conflict_and_field_wide_addendum_update_scenarios():
    fixture = json.loads(Path("tests/fixtures/structured_extraction/value-level-acceptance.json").read_text(encoding="utf-8"))
    for case in fixture["scenarios"]:
        record = StructuredExtractor().extract(case["bid_id"], [_source_evidence(item, case["bid_id"]) for item in case["evidence"]])
        field = record.fields[case["field"]]
        assert field.status == case["expected_status"], case["name"]
        if case["expected_status"] == "not_found":
            assert field.value is None
        elif case["expected_status"] == "review_required":
            assert field.value is None
            assert {citation.file for citation in field.citations} == set(case["expected_citations"])
        else:
            assert field.value == case["expected_value"]
            change = next(change for change in record.addendum_changes if change.field == case["field"])
            assert change.previous_value == case["previous_value"]
            assert change.current_value == case["expected_value"]
            assert change.previous_citations[0].file == "base.pdf"
            assert change.current_citations[0].file == "addendum-1.pdf"


def test_api_workflow_retrieves_all_matching_records_for_extraction_lists():
    bid_records = [
        {
            "record_id": f"document-{index}",
            "bid_id": "Bid1",
            "source_file": f"documents-{index}.pdf",
            "page_number": index + 1,
            "source_locator": {"page": index + 1},
            "doc_type": "rfp",
            "text": f"Required documents: Affidavit Form {index:02d}.",
        }
        for index in range(15)
    ]
    unrelated_records = [
        {"record_id": f"other-{index}", "bid_id": "OtherBid", "text": "Unrelated source."}
        for index in range(25)
    ]
    records = bid_records + unrelated_records

    class RecordSearch:
        def __init__(self, corpus_records):
            self.requested_limits = []
            self.records = corpus_records

        def search(self, query):
            self.requested_limits.append(query.top_k)
            filtered = [record for record in self.records if record["bid_id"] in query.filters["bid_id"]]
            return {
                "results": [{"record": record, "authority_status": "current"} for record in filtered[:query.top_k]],
                "diagnostics": [],
                "query_variants": {},
            }

    class Trace:
        def run_tool(self, _name, _inputs, operation, *, output_summary=None):
            return operation()

        def event(self, *_args, **_kwargs):
            pass

    workflow = object.__new__(AnalysisWorkflow)
    workflow.retrieval = RetrievalAgent(search_service=RecordSearch(records))
    data = {
        "mode": "extraction",
        "retry_fields": [],
        "plan": {"field_groups": {"documents": ["Any Additional Documentation Required"]}},
        "goal": "extract complete bid record",
        "bid_ids": ["Bid1"],
        "diagnostics": [],
        "retrieved_evidence": [],
        "_trace": Trace(),
    }

    result = workflow._retrieval(data)

    assert workflow.retrieval.search_service.requested_limits == [len(bid_records)]
    assert len(result["retrieved_evidence"]) == len(bid_records)


def test_real_bid2_folder_matches_value_matrix_with_values_citations_and_statuses():
    root = Path(__file__).resolve().parents[2]
    report = IngestionPipeline().process(root / "Initial_docs" / "Bid2", bid_id="Bid2")
    evidence = [
        {
            "record": {
                "source_file": chunk.source_file,
                "page_number": chunk.page_number,
                "source_locator": chunk.source_locator,
                "bid_id": chunk.bid_id,
                "doc_type": chunk.doc_type,
                "addendum_number": chunk.addendum_number,
                "content_kind": chunk.content_kind,
                "section_title": chunk.section_title,
                "text": chunk.text,
            },
            "authority_status": "current",
        }
        for chunk in report.chunks
    ]
    fixture = json.loads(Path("tests/fixtures/structured_extraction/value-level-acceptance.json").read_text(encoding="utf-8"))
    case = fixture["bids"]["Bid2"]
    record = StructuredExtractor().extract("Bid2", evidence)

    assert len(record.fields) == 20
    for name in CANONICAL_FIELDS:
        field = record.fields[name]
        if name in case["not_found"]:
            assert field.status == "not_found", (name, field)
            assert field.value is None
            assert field.citations == []
            continue

        expected = case["supported"][name]
        if name == "Bid Summary":
            assert field.status == "supported"
            actual_sentences = re.split(r"(?<=[.!?])\s+", field.value.strip())
            expected_sentences = re.split(r"(?<=[.!?])\s+", expected["value"].strip())
            product_sentence = re.compile(r"Requested products include (.+)\.$")
            actual_product = next(sentence for sentence in actual_sentences if product_sentence.fullmatch(sentence))
            expected_product = next(sentence for sentence in expected_sentences if product_sentence.fullmatch(sentence))
            assert [sentence for sentence in actual_sentences if sentence != actual_product] == [
                sentence for sentence in expected_sentences if sentence != expected_product
            ]
            actual_products = product_sentence.fullmatch(actual_product).group(1).split(", ")
            expected_products = product_sentence.fullmatch(expected_product).group(1).split(", ")
            assert sorted(actual_products, key=str.casefold) == sorted(expected_products, key=str.casefold)
            assert 3 <= len(actual_sentences) <= 6
            assert _expected_citation_keys(expected["citations"]) <= _citation_keys(field.citations)
            assert _citations_are_locatable(field.citations)
            continue
        if name == "Product Specification":
            assert field.status == "supported"
            actual_values = [item.value for item in field.value]
            actual_text = " ".join(actual_values).casefold()
            for expected_item in expected["items"]:
                expected_value = expected_item["value"] if isinstance(expected_item, dict) else expected_item
                assert str(expected_value).casefold() in actual_text, (name, expected_value)
                if isinstance(expected_item, dict):
                    assert _expected_citation_keys(expected_item.get("citations", [])) <= _citation_keys(field.citations), (name, expected_value)
            assert _citations_are_locatable(field.citations)
            continue
        outcome = _matrix_outcome(case, name, field)
        assert outcome["outcome"] == "supported", (name, outcome)
        assert _citations_are_locatable(field.citations), (name, field.citations)
        if "items" in expected:
            actual_by_value = {item.value.casefold(): item for item in field.value}
            for expected_item in expected["items"]:
                value = expected_item["value"] if isinstance(expected_item, dict) else expected_item
                wanted_citations = expected_item.get("citations", []) if isinstance(expected_item, dict) else expected.get("citations", [])
                actual_item = actual_by_value[str(value).casefold()]
                assert _expected_citation_keys(wanted_citations) <= _citation_keys(actual_item.citations), (name, value)
                assert _citations_are_locatable(actual_item.citations), (name, value)
        else:
            assert _expected_citation_keys(expected["citations"]) <= _citation_keys(field.citations), (name, field)
