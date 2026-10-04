from pathlib import Path

from src.agents.report_agent import synthesize_answer
from src.ingestion.pipeline import IngestionPipeline
from src.ingestion.retention import load_retention_manifest
from src.ingestion.serialization import report_dict
from src.search.index import IndexService
from src.search.models import SearchQuery, as_dict
from src.search.search import SearchService
from src.search.storage import CorpusStore
from tests.fixtures.robustness.document_provenance_factory import create_robustness_document_folder


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "tests" / "fixtures" / "retention" / "robustness-long-document.json"


def test_table_and_long_document_content_retrieves_with_source_locations(tmp_path):
    bid_folder = create_robustness_document_folder(tmp_path)
    manifest = load_retention_manifest(MANIFEST_PATH)
    report = IngestionPipeline().process(bid_folder, bid_id="RobustDocs", retention_manifest=MANIFEST_PATH)

    assert report.retention_report.text.coverage == 1.0
    assert report.retention_report.tables.coverage == 1.0
    report_data = report_dict(report)
    usable_documents = [item for item in report_data["documents"] if item["status"] in {"parsed", "partial"}]
    usable_paths = {item["relative_path"] for item in usable_documents}
    chunks = [
        chunk
        for chunk in report_data["chunks"]
        if chunk["source_locator"].get("relative_path", chunk["source_file"]) in usable_paths
    ]
    store = CorpusStore(tmp_path / "corpus.json")
    IndexService(store).update({
        "bid_id": "RobustDocs",
        "source_manifest": [{"relative_path": path} for path in sorted(usable_paths)],
        "chunks": chunks,
    })
    search = SearchService(store.load().records)

    table_response = search.search(
        SearchQuery("submission deadline", filters={"bid_id": ["RobustDocs"]}),
        configuration="keyword-only",
    )
    assert table_response["results"]
    table_answer = synthesize_answer(
        "What is the submission deadline?",
        [as_dict(item) for item in table_response["results"]],
    )
    assert table_answer["found"] is True
    assert "September 30, 2026" in table_answer["answer"]
    table_citation = table_answer["citations"][0]
    assert table_citation["file"] == "table-document.html"
    assert table_citation["page"] is None
    assert table_citation["locator"]["relative_path"] == "procurement/table-document.html"
    assert table_citation["locator"]["table_id"]
    assert table_citation["locator"]["element_index"] is not None

    pdf_response = search.search(
        SearchQuery("LONG_PAGE_2_START", filters={"bid_id": ["RobustDocs"]}),
        configuration="keyword-only",
    )
    assert pdf_response["results"]
    pdf_record = next(
        item.record for item in pdf_response["results"] if "LONG_PAGE_2_START" in item.record.text
    )
    assert pdf_record.source_file == "long-document.pdf"
    assert pdf_record.source_locator["relative_path"] == "technical/long-document.pdf"
    assert 2 in pdf_record.source_locator["page_numbers"]
    assert any(segment["page_number"] == 2 for segment in pdf_record.source_locator["source_segments"])
