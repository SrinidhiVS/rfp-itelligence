"""Synchronize the persisted lexical corpus into the local Chroma index."""

from __future__ import annotations

import os

from .config import chroma_index_path
from .embedding_models import EmbeddingConfig
from .embeddings import SentenceTransformerProvider
from .storage import CorpusStore
from .vector_store import VectorStore


def sync_chroma_index(store: CorpusStore, provider=None) -> dict[str, object]:
    """Embed the stored corpus into Chroma using the configured provider.

    Args:
        store: Corpus persistence adapter whose records and source manifest
            form the input to vector synchronization.
        provider: Optional embedding provider. When omitted, a
            ``SentenceTransformerProvider`` is created using
            ``RFP_EMBEDDING_MODEL`` or ``all-MiniLM-L6-v2``.

    Returns:
        Vector-store update mapping with embedded/skipped/unchanged/replaced/
        removed/failed counts and diagnostics. Any exception is converted into
        a failed result with one ``automatic Chroma sync failed`` diagnostic.
    """
    try:
        embedding_provider = provider or SentenceTransformerProvider(
            EmbeddingConfig(model_name=os.getenv("RFP_EMBEDDING_MODEL", "all-MiniLM-L6-v2"))
        )
        corpus = store.load()
        return VectorStore(chroma_index_path()).update_from_records(
            corpus.records,
            embedding_provider,
            source_manifest=corpus.source_manifest,
        )
    except Exception as exc:
        return {
            "embedded": 0,
            "skipped_empty": 0,
            "unchanged": 0,
            "replaced": 0,
            "removed": 0,
            "failed": 1,
            "diagnostics": [f"automatic Chroma sync failed: {exc}"],
        }