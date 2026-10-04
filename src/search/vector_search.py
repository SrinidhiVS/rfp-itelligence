"""Adapt vector-store matches into the common ranked-evidence response shape."""

from __future__ import annotations

from typing import Any

from .embeddings import EmbeddingProvider
from .models import IndexRecord, RankedEvidence, SearchQuery
from .vector_store import VectorIndexError, VectorStore


class VectorSearch:
    """Embed a query, retrieve nearest vectors, and map them to search results.

    Args:
        store: Persistent vector store implementing ``query``.
        provider: Embedding provider whose configuration must match the index.
    """

    def __init__(self, store: VectorStore, provider: EmbeddingProvider):
        """Bind a persistent vector store to its embedding provider."""
        self.store = store
        self.provider = provider

    def search(self, query: SearchQuery) -> dict[str, Any]:
        """Return nearest vector matches using the standard search envelope.

        Args:
            query: Search query; text is embedded and its ``top_k`` and filters
                are passed to the vector store.

        Returns:
            Mapping with ``results`` (ranked evidence list), ``found`` (bool),
            and ``diagnostics`` (list of strings). Supported vector/runtime
            errors produce an empty result and the error message as a
            diagnostic; no matches use ``no_supporting_evidence``.
        """
        try:
            query_vector = self.provider.embed([query.text])[0]
            ranked = self.store.query(query_vector, query.top_k, query.filters, self.provider.config)
        except (VectorIndexError, RuntimeError, ValueError) as exc:
            return {"results": [], "found": False, "diagnostics": [str(exc)]}
        results = []
        for rank, (vector_record, score) in enumerate(ranked, 1):
            index_record = IndexRecord(record_id=vector_record.record_id, chunk_id=vector_record.record_id, scope_id=vector_record.scope_id, content_fingerprint=vector_record.content_fingerprint, text=vector_record.text, bid_id=vector_record.bid_id, source_file=vector_record.source_file, page_number=vector_record.page_number, section_title=vector_record.section_title, doc_type=vector_record.doc_type, addendum_number=vector_record.addendum_number, document_date=vector_record.document_date, source_locator=vector_record.source_locator, status="current", content_kind=vector_record.content_kind)
            results.append(RankedEvidence(record_id=vector_record.record_id, rank=rank, score=score, record=index_record, retrieval_methods=["semantic"], source_completeness="complete", authority_status=vector_record.authority_status, superseded_by=vector_record.superseded_by))
        return {"results": results, "found": bool(results), "diagnostics": [] if results else ["no_supporting_evidence"]}
