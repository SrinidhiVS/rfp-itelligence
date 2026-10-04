"""Embedding-provider protocol and sentence-transformer implementations."""

from __future__ import annotations

from typing import Any, Protocol

from .embedding_models import EmbeddingConfig


class EmbeddingProvider(Protocol):
    """Structural interface for configured text-to-vector providers.

    Implementations expose an ``EmbeddingConfig`` as ``config`` and return one
    numeric vector per input string from ``embed``.
    """

    config: EmbeddingConfig

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one fixed-dimension numeric vector per nonblank input string."""
        ...


class EmbeddingUnavailable(RuntimeError):
    """Raised when an embedding model cannot be loaded or run."""

    pass


class SentenceTransformerProvider:
    """Generate normalized sentence-transformer embeddings in batches.

    Args:
        config: Model and embedding settings. Defaults to the configured
            ``EmbeddingConfig`` defaults.
        model: Optional already-loaded model object, useful for injection and
            tests; otherwise the configured sentence-transformer is loaded.

    Raises:
        EmbeddingUnavailable: If the dependency or configured model cannot be
            loaded.
    """

    def __init__(self, config: EmbeddingConfig | None = None, model: Any = None):
        """Load configured model or retain an injected model instance."""
        self.config = config or EmbeddingConfig()
        if model is not None:
            self.model = model
            return
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise EmbeddingUnavailable("sentence-transformers is not installed") from exc
        try:
            self.model = SentenceTransformer(self.config.model_name)
        except Exception as exc:
            raise EmbeddingUnavailable(f"unable to load embedding model {self.config.model_name}: {exc}") from exc

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Encode each nonblank input string as a numeric vector.

        Args:
            texts: Ordered list of document/query strings; empty or whitespace
                entries are rejected.

        Returns:
            A list of float lists with one consistent dimension per row. An
            empty input list returns an empty list.

        Raises:
            ValueError: If an input is blank or returned vector dimensions
                differ.
            EmbeddingUnavailable: If model encoding fails.
        """
        non_empty = [text for text in texts if text and text.strip()]
        if len(non_empty) != len(texts):
            raise ValueError("empty chunks cannot be embedded")
        try:
            vectors = self.model.encode(non_empty, normalize_embeddings=self.config.normalize, batch_size=self.config.batch_size, convert_to_numpy=True)
            rows = vectors.tolist()
        except Exception as exc:
            raise EmbeddingUnavailable(f"embedding failed: {exc}") from exc
        if not rows:
            return []
        dimension = len(rows[0])
        if any(len(row) != dimension for row in rows):
            raise ValueError("embedding provider returned inconsistent dimensions")
        return rows


class DeterministicEmbeddingProvider:
    """Create stable hash-derived embeddings for offline tests.

    Args:
        dimension: Number of float components in every output vector; defaults
            to 8.

    This provider is deterministic and is intended for tests, not semantic
    quality in production.
    """

    def __init__(self, dimension: int = 8):
        """Configure deterministic output width for offline embeddings."""
        self.config = EmbeddingConfig(provider="deterministic-test", model_name="deterministic", dimension=dimension)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Convert nonblank strings into fixed-width SHA-256-derived vectors.

        Args:
            texts: Ordered strings to encode; blank strings are rejected.

        Returns:
            One list of ``dimension`` floats in the range 0 to 1 per string.

        Raises:
            ValueError: If any input string is blank.
        """
        import hashlib
        vectors = []
        for text in texts:
            if not text or not text.strip():
                raise ValueError("empty chunks cannot be embedded")
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            vectors.append([digest[index] / 255 for index in range(self.config.dimension or 8)])
        return vectors
