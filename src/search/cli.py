"""Command-line interface for indexing, searching, answering, and evaluation."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .config import chroma_index_path, index_path
from .index import IndexService
from .models import as_dict
from .qa import QAService
from .query import make_query
from .search import SearchService
from .storage import CorpusStore
from .evaluation import evaluate, load_cases, validate_cases


def _vector_readiness(vector_search, corpus_records=None) -> dict:
    """Check vector-index availability and consistency with the active corpus.

    Args:
        vector_search: Optional vector search adapter with a store and provider.
        corpus_records: Optional active lexical records used for ID and content
            consistency checks.

    Returns:
        Readiness mapping with ``available``, ``actual_mode``, and
        ``diagnostics``. A ready index additionally reports path, model,
        provider, dimension, record count, and update timestamp.
    """
    if vector_search is None:
        return {"available": False, "actual_mode": "unavailable", "diagnostics": ["local vector index is not configured"]}
    try:
        records, manifest = vector_search.store.load(vector_search.provider.config)
    except (OSError, RuntimeError, ValueError) as exc:
        return {"available": False, "actual_mode": "unavailable", "diagnostics": [str(exc)]}
    if not records:
        return {"available": False, "actual_mode": "unavailable", "diagnostics": ["local vector index has no records"]}
    if corpus_records is not None:
        indexed = {item.record_id: item for item in corpus_records}
        stored = {item.record_id: item for item in records}
        if indexed.keys() != stored.keys() or any(
            (item.bid_id, item.source_file, item.page_number, item.text, item.content_fingerprint)
            != (stored[record_id].bid_id, stored[record_id].source_file, stored[record_id].page_number, stored[record_id].text, stored[record_id].content_fingerprint)
            for record_id, item in indexed.items() if record_id in stored
        ):
            return {"available": False, "actual_mode": "unavailable", "diagnostics": ["local vector index does not match the active corpus"]}
    return {
        "available": True,
        "actual_mode": "indexed-vector",
        "diagnostics": [],
        "index_path": str(vector_search.store.path),
        "model_name": manifest.model_name,
        "provider": manifest.provider,
        "dimension": manifest.dimension,
        "record_count": len(records),
        "updated_at": manifest.updated_at,
    }


def _vector_search():
    """Create a vector search adapter when a local Chroma index is present.

    Returns:
        Configured ``VectorSearch`` instance, or ``None`` when the index path
        is absent or provider initialization fails.
    """
    if not chroma_index_path().exists():
        return None
    try:
        from .embeddings import SentenceTransformerProvider
        from .vector_search import VectorSearch
        from .vector_store import VectorStore
        return VectorSearch(VectorStore(chroma_index_path()), SentenceTransformerProvider())
    except Exception:
        return None


def _service() -> tuple[IndexService, SearchService]:
    """Build index and search services from environment-configured paths.

    Returns:
        Pair of ``IndexService`` and ``SearchService`` instances using the
        current lexical records and optional local vector search.
    """
    store = CorpusStore(index_path())
    indexer = IndexService(store)
    vector_search = _vector_search()
    diagnostic = None if vector_search else "local Chroma vector index is missing or its embedding provider is unavailable"
    return indexer, SearchService(indexer.records(), vector_search=vector_search, vector_diagnostic=diagnostic)


def main() -> int:
    """Parse CLI arguments, dispatch a search operation, and print JSON.

    Supported subcommands are ``index``, ``rebuild``, ``search``, ``ask``,
    ``evaluate``, and ``vector-index``. Inputs are command-line arguments and
    JSON files; successful responses are pretty-printed JSON on stdout.

    Returns:
        Process status code: 0 on success, 1 when required vector evaluation
        is unavailable or vector indexing reports a failed update.
    """
    parser = argparse.ArgumentParser(description="RFP search engine")
    subparsers = parser.add_subparsers(dest="command", required=True)
    index_parser = subparsers.add_parser("index")
    index_parser.add_argument("--input", type=Path, required=True)
    rebuild_parser = subparsers.add_parser("rebuild")
    rebuild_parser.add_argument("--input", type=Path, required=True)
    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("text")
    search_parser.add_argument("--bid-id")
    search_parser.add_argument("--doc-type")
    search_parser.add_argument("--addendum-number", type=int)
    search_parser.add_argument("--top-k", type=int, default=5)
    ask_parser = subparsers.add_parser("ask")
    ask_parser.add_argument("text")
    ask_parser.add_argument("--bid-id")
    eval_parser = subparsers.add_parser("evaluate")
    eval_parser.add_argument("--cases", type=Path, required=True)
    eval_parser.add_argument("--top-k", type=int, default=5)
    eval_parser.add_argument("--warm-up", action="store_true", help="measure model/index initialization separately before timing queries")
    vector_parser = subparsers.add_parser("vector-index")
    vector_parser.add_argument("--model", default="all-MiniLM-L6-v2")
    vector_parser.add_argument("--rebuild", action="store_true", help="re-embed every current source scope")
    args = parser.parse_args()
    if args.command in {"index", "rebuild"}:
        request = json.loads(args.input.read_text(encoding="utf-8"))
        result = IndexService(CorpusStore(index_path())).update(request, full_rebuild=args.command == "rebuild")
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "evaluate":
        indexer, search = _service()
        corpus = indexer.store.load()
        vector_status = _vector_readiness(search.vector_search, corpus.records)
        if not vector_status["available"]:
            print(json.dumps({"error": "indexed semantic evaluation unavailable", "vector_index": vector_status}, indent=2))
            return 1
        cases = load_cases(args.cases)
        validate_cases(cases, corpus.records)
        model_name = os.getenv("RFP_RERANK_MODEL")
        report = evaluate(search, cases, ["semantic-only", "hybrid"], args.top_k, warm_up=args.warm_up, run_context={
            "case_set_path": str(args.cases),
            "corpus": {"corpus_id": corpus.corpus_id, "schema_version": corpus.schema_version, "record_count": len(corpus.records), "updated_at": corpus.updated_at, "index_path": str(indexer.store.path)},
            "vector_index": vector_status,
        }, require_vectors=True, vector_status=vector_status)
        reranker_states = {row["reranker_status"] for row in report["configurations"]}
        reranker_status = "heuristic-fallback" if "heuristic-fallback" in reranker_states else "model" if "model" in reranker_states else "not-used" if model_name else "heuristic"
        report["run_context"]["reranker"] = {"model_name": model_name, "status": reranker_status}
        report["vector_index"] = vector_status
        print(json.dumps(report, indent=2))
        return 0
    if args.command == "vector-index":
        from .embedding_models import EmbeddingConfig
        from .embeddings import SentenceTransformerProvider
        from .vector_store import VectorStore
        provider = SentenceTransformerProvider(EmbeddingConfig(model_name=args.model))
        corpus = CorpusStore(index_path()).load()
        result = VectorStore(chroma_index_path()).update_from_records(
            corpus.records,
            provider,
            full_rebuild=args.rebuild,
            source_manifest=corpus.source_manifest,
        )
        print(json.dumps(result, indent=2))
        return 1 if result["failed"] else 0
    indexer, search = _service()
    filters = {key: value for key, value in {"bid_id": getattr(args, "bid_id", None), "doc_type": getattr(args, "doc_type", None), "addendum_number": getattr(args, "addendum_number", None)}.items() if value is not None}
    query = make_query({"text": args.text, "filters": filters, "top_k": getattr(args, "top_k", 5), "mode": "answer" if args.command == "ask" else "search"})
    if args.command == "search":
        print(json.dumps(as_dict(search.search(query)), indent=2))
    elif args.command == "ask":
        print(json.dumps(as_dict(QAService(search).answer(query)), indent=2))
    else:
        raise ValueError(f"Unsupported command: {args.command}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
