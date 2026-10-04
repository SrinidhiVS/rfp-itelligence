from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from src.ingestion.pipeline import IngestionPipeline
from src.ingestion.serialization import report_dict
from src.search.index import IndexService
from src.search.models import as_dict
from src.search.storage import CorpusStore

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "supp_tasks_coverage.json"


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).casefold().strip()


def build_supp_tasks_corpus(corpus_path: Path) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    store = CorpusStore(corpus_path)
    index = IndexService(store)

    for bid_id in ("Bid1", "Bid2"):
        report = report_dict(IngestionPipeline().process(ROOT / "Initial_docs" / bid_id, bid_id=bid_id))
        usable_documents = [item for item in report["documents"] if item["status"] in {"parsed", "partial"}]
        usable_paths = {item["relative_path"] for item in usable_documents}
        chunks = [
            chunk
            for chunk in report["chunks"]
            if chunk["source_locator"].get("relative_path", chunk["source_file"]) in usable_paths
            and chunk["text"].strip()
        ]
        index.update({
            "bid_id": bid_id,
            "source_manifest": [{"relative_path": path} for path in sorted(usable_paths)],
            "chunks": chunks,
        })

    corpus_records = store.load().records
    evidence_by_key: dict[str, dict[str, Any]] = {}
    for item in fixture["records"]:
        source = item["source"]
        expected_text = _normalize(source["expected_excerpt"])
        matches = []
        for record in corpus_records:
            locator = record.source_locator
            source_pages = set(locator.get("page_numbers", []))
            source_pages.update(
                segment.get("page_number")
                for segment in locator.get("source_segments", [])
                if segment.get("page_number") is not None
            )
            if record.page_number is not None:
                source_pages.add(record.page_number)
            if (
                record.bid_id != source["bid_id"]
                or locator.get("relative_path") != source["relative_path"]
                or source["page_number"] not in source_pages
                or any(locator.get(key) != value for key, value in source.get("source_locator", {}).items())
                or expected_text not in _normalize(record.text)
            ):
                continue
            matches.append(record)
        if len(matches) != 1:
            raise AssertionError(f"{item['evidence_key']}: expected one source-verified record, found {len(matches)}")
        evidence_by_key[item["evidence_key"]] = {
            "authority_status": item["authority_status"],
            "record": as_dict(matches[0]),
        }

    return evidence_by_key, [as_dict(record) for record in corpus_records]
