from pathlib import Path

import pymupdf

from src.ingestion.pipeline import IngestionPipeline
from src.ingestion.serialization import report_dict
from src.search.index import IndexService
from src.search.models import SearchQuery
from src.search.search import SearchService
from src.search.storage import CorpusStore


def test_mixed_inputs_keep_usable_evidence_and_locate_failures(tmp_path: Path) -> None:
    source_root = tmp_path / "mixed-bid"
    source_root.mkdir()
    (source_root / "valid.html").write_text(
        "<html><body><h1>Solicitation</h1><p>Submission deadline: December 9, 2026</p></body></html>",
        encoding="utf-8",
    )
    (source_root / "broken.pdf").write_bytes(b"not a valid PDF")
    (source_root / "unsupported.txt").write_text("Unsupported source", encoding="utf-8")
    (source_root / "empty.html").write_text("", encoding="utf-8")

    partial_pdf = pymupdf.open()
    partial_pdf.new_page().insert_text((72, 72), "Product specification: Portable air monitor")
    partial_pdf.new_page()
    partial_pdf.save(source_root / "partial.pdf")
    partial_pdf.close()

    report = report_dict(IngestionPipeline().process(source_root, bid_id="MixedInputs"))
    files_by_path = {document["relative_path"]: document for document in report["documents"]}
    assert report["status"] == "incomplete"
    assert files_by_path["broken.pdf"]["status"] == "failed"
    assert files_by_path["unsupported.txt"]["status"] == "unsupported"
    assert files_by_path["empty.html"]["status"] in {"failed", "partial"}
    assert files_by_path["partial.pdf"]["status"] == "partial"

    diagnostic_paths = {
        (item.get("source_locator") or {}).get("relative_path")
        for item in report["diagnostics"]
    }
    assert {"broken.pdf", "unsupported.txt", "empty.html", "partial.pdf"} <= diagnostic_paths

    corpus_path = tmp_path / "corpus.json"
    store = CorpusStore(corpus_path)
    usable_paths = {
        document["relative_path"]
        for document in report["documents"]
        if document["status"] in {"parsed", "partial"}
    }
    chunks = [
        chunk
        for chunk in report["chunks"]
        if chunk["source_locator"].get("relative_path", chunk["source_file"]) in usable_paths
    ]
    IndexService(store).update({
        "bid_id": "MixedInputs",
        "source_manifest": [{"relative_path": path} for path in sorted(usable_paths)],
        "chunks": chunks,
    })
    records = store.load().records
    assert any(record.source_file == "valid.html" and "December 9, 2026" in record.text for record in records)
    assert any(record.source_file == "partial.pdf" and "Portable air monitor" in record.text for record in records)
    assert all(not record.diagnostic_ids for record in records if record.source_file == "valid.html")

    response = SearchService(records).search(
        SearchQuery("submission deadline December 9 2026", filters={"bid_id": ["MixedInputs"]}),
        configuration="keyword-only",
    )
    assert response["results"]
    assert response["results"][0].record.source_file == "valid.html"
    assert all(item.record.bid_id == "MixedInputs" for item in response["results"])
