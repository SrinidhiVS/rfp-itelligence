"""Provide workflow-scoped search over lexical and optional Chroma evidence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.search.config import index_path
from src.search.config import chroma_index_path
from src.search.models import SearchQuery, as_dict
from src.search.search import SearchService
from src.search.storage import CorpusStore


class RetrievalAgent:
    """Load corpus/vector search services and expose bid-filtered retrieval.

    Args:
        search_service: Optional injected search implementation.
        corpus_path: Optional lexical corpus JSON path used for loading/refresh.
    """

    def __init__(self, search_service: SearchService | None = None, corpus_path: Path | None = None):
        """Load the corpus and initialize optional local vector search."""
        self.semantic_enabled = False
        self.semantic_diagnostic: str | None = None
        self._owns_search_service = search_service is None
        self._corpus_path = corpus_path or index_path()
        if search_service is None:
            corpus = CorpusStore(self._corpus_path).load()
            vector_search = None
            vector_path = chroma_index_path()
            if vector_path.exists():
                try:
                    from src.search.embedding_models import EmbeddingConfig
                    from src.search.embeddings import SentenceTransformerProvider
                    from src.search.vector_search import VectorSearch
                    from src.search.vector_store import VectorStore

                    provider = SentenceTransformerProvider(EmbeddingConfig())
                    vector_search = VectorSearch(VectorStore(vector_path), provider)
                    self.semantic_enabled = True
                except Exception as exc:
                    self.semantic_diagnostic = str(exc)
            else:
                self.semantic_diagnostic = "local Chroma vector index is missing"
            search_service = SearchService(
                corpus.records,
                vector_search=vector_search,
                vector_diagnostic=self.semantic_diagnostic,
            )
        self.search_service = search_service

    def refresh(self) -> None:
        """Reload records for internally owned search services."""
        if self._owns_search_service:
            self.search_service.records = CorpusStore(self._corpus_path).load().records

    def status(self) -> dict[str, object]:
        """Return whether semantic search initialized and any setup diagnostic."""
        return {"semantic_enabled": self.semantic_enabled, "semantic_diagnostic": self.semantic_diagnostic}

    def search(
        self,
        text: str,
        bid_ids: list[str],
        *,
        top_k: int | None = 10,
        addendum_only: bool = False,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Search evidence constrained to bid IDs, filters, and addendum scope.

        Args:
            text: Search query text.
            bid_ids: Bid IDs included in the search; empty means no bid filter.
            top_k: Result limit; ``None`` expands to the count of scoped records.
            addendum_only: If true, constrain document type to addendum.
            filters: Additional query filters merged with bid/addendum filters.

        Returns:
            Mapping with JSON-compatible ``results``, string ``diagnostics``,
            and serialized ``query_variants``.
        """
        if top_k is None:
            records = getattr(self.search_service, "records", [])
            scoped_count = sum(
                1
                for record in records
                if not bid_ids
                or (record.get("bid_id") if isinstance(record, dict) else getattr(record, "bid_id", None)) in bid_ids
            )
            top_k = max(1, scoped_count)
        search_filters = dict(filters or {})
        if bid_ids:
            search_filters["bid_id"] = bid_ids
        if addendum_only:
            search_filters["doc_type"] = "addendum"
        response = self.search_service.search(SearchQuery(text=text, filters=search_filters, top_k=top_k))
        return {
            "results": [as_dict(item) for item in response["results"]],
            "diagnostics": response["diagnostics"],
            "query_variants": as_dict(response["query_variants"]),
        }
