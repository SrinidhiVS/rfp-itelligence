"""Dispatch top-level ingestion and search command-line operations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.ingestion.logging import configure_logging
from src.search.cli import main as search_main
from src.ingestion.pipeline import IngestionPipeline
from src.ingestion.serialization import report_dict
from src.search.chroma_sync import sync_chroma_index
from src.search.config import index_path
from src.search.identity import normalize_relative_path, scope_id
from src.search.index import IndexService
from src.search.storage import CorpusStore


def main() -> int:
    """Run search subcommands or ingest a bid folder and update its indexes.

    Returns:
        Process status code 0 when ingestion/search completes successfully, or
        1 when ingestion fails or vector synchronization reports failure.
        Ingestion writes ``processing-report.json`` plus a compact JSON summary
        to stdout; search commands are delegated to the search CLI.
    """
    import sys
    if len(sys.argv) > 1 and sys.argv[1] in {"index", "rebuild", "search", "ask", "evaluate", "vector-index"}:
        return search_main()
    parser = argparse.ArgumentParser(description="Ingest an RFP bid folder")
    parser.add_argument("command", choices=["ingest"])
    parser.add_argument("folder", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bid-id")
    parser.add_argument("--retention-manifest", type=Path)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    configure_logging(args.verbose)
    if args.retention_manifest is None:
        report = IngestionPipeline().process(args.folder, bid_id=args.bid_id)
    else:
        report = IngestionPipeline().process(
            args.folder,
            bid_id=args.bid_id,
            retention_manifest=args.retention_manifest,
        )
    payload = report_dict(report)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "processing-report.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    index_result = None
    vector_result = None
    usable_statuses = {"parsed", "partial"}
    usable_sources = {
        document["relative_path"]
        for document in payload["documents"]
        if document["status"] in usable_statuses
    }
    chunks = [
        chunk
        for chunk in payload["chunks"]
        if chunk["text"].strip()
        and chunk["source_locator"].get("relative_path", chunk["source_file"]) in usable_sources
    ]
    if chunks:
        bid_id = args.bid_id or args.folder.name
        failed_sources = [
            scope_id(bid_id, normalize_relative_path(document["relative_path"]))
            for document in payload["documents"]
            if document["status"] in {"failed", "unsupported"}
        ]
        store = CorpusStore(index_path())
        index_result = IndexService(store).update({
            "bid_id": bid_id,
            "source_manifest": [{"relative_path": source} for source in sorted(usable_sources)],
            "chunks": chunks,
            "preserve_scopes": failed_sources,
        })
        vector_result = sync_chroma_index(store)
    print(json.dumps({
        "bid_id": report.bid_id,
        "status": report.status,
        "files": report.discovered_file_count,
        "index": index_result,
        "vector_index": vector_result,
    }))
    return 0 if report.status != "failed" and not (vector_result and vector_result.get("failed")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
