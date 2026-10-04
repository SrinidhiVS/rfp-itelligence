"""Index staged bid folders and report corpus/vector readiness to workflows."""

from __future__ import annotations

import os
from pathlib import Path

from src.ingestion.pipeline import IngestionPipeline
from src.ingestion.serialization import report_dict
from src.search.config import index_path
from src.search.identity import normalize_relative_path, scope_id
from src.search.index import IndexService
from src.search.storage import CorpusStore
from src.search.chroma_sync import sync_chroma_index


def ensure_index(bid_ids: list[str], path: Path | None = None, submitted_bid_folders: dict[str, str] | None = None) -> dict:
    """Validate, ingest, and index submitted bid folders, then sync vectors.

    Args:
        bid_ids: Requested bid identifiers used to limit folder ingestion.
        path: Optional lexical index JSON path; defaults to search config.
        submitted_bid_folders: Optional bid-ID to staged-folder path mapping.
            Folders must be direct children of ``RFP_SUBMISSION_ROOT``.

    Returns:
        Mapping with available/missing bid IDs, indexed/updated flags,
        optional vector-index update counts, and diagnostics. Invalid folders
        are reported rather than indexed.
    """
    store = CorpusStore(path or index_path())
    diagnostics: list[str] = []
    updated = False
    staging_root = Path(os.getenv("RFP_SUBMISSION_ROOT", "output/imported-bids")).resolve()
    for bid_id, reference in (submitted_bid_folders or {}).items():
        folder = Path(reference).resolve()
        if bid_id not in bid_ids or folder.parent != staging_root or folder.name != bid_id or not folder.is_dir():
            diagnostics.append(f"unauthorized or missing staged folder for {bid_id}")
            continue
        report = report_dict(IngestionPipeline().process(folder, bid_id=bid_id))
        failed = [document for document in report["documents"] if document["status"] in {"failed", "unsupported", "partial"}]
        diagnostics.extend(f"{bid_id}/{document['relative_path']}: {document['status']}" for document in failed)
        if report["chunks"]:
            usable = {document["relative_path"] for document in report["documents"] if document["status"] in {"parsed", "partial"}}
            chunks = [chunk for chunk in report["chunks"] if chunk["source_locator"].get("relative_path", chunk["source_file"]) in usable and chunk["text"].strip()]
            if chunks:
                preserved = [scope_id(bid_id, normalize_relative_path(document["relative_path"])) for document in failed if document["status"] in {"failed", "unsupported"}]
                IndexService(store).update({"bid_id": bid_id, "source_manifest": [{"relative_path": source} for source in sorted(usable)], "chunks": chunks, "preserve_scopes": preserved})
                updated = True
        else:
            diagnostics.append(f"no usable evidence for {bid_id}")
    vector_index = sync_chroma_index(store) if updated else None
    corpus = store.load()
    available = sorted({record.bid_id for record in corpus.records})
    missing = [bid_id for bid_id in bid_ids if bid_id not in available]
    return {
        "available_bid_ids": available,
        "missing_bid_ids": missing,
        "indexed": not missing and not diagnostics,
        "updated": updated,
        "vector_index": vector_index,
        "diagnostics": diagnostics + [f"no indexed evidence for {bid_id}" for bid_id in missing],
    }
