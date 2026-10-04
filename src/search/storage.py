"""Persist the lexical search corpus as atomically replaced JSON."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from .models import IndexedCorpus, IndexRecord, SourceFileScope, as_dict


class CorpusStore:
    """Load and save an ``IndexedCorpus`` at a JSON file path.

    Args:
        path: Destination JSON file. Its parent directory is created on save.
    """

    def __init__(self, path: Path):
        """Store the destination path for corpus JSON persistence."""
        self.path = path

    def load(self) -> IndexedCorpus:
        """Load and parse the corpus file, or return an empty default corpus.

        Returns:
            Reconstructed ``IndexedCorpus`` with typed record and source-scope
            objects. A missing file yields corpus ID ``rfp-corpus`` and schema
            version ``1``.

        Raises:
            OSError: If the file cannot be read.
            ValueError: If its JSON is malformed or required schema fields are
                absent.
        """
        if not self.path.exists():
            return IndexedCorpus("rfp-corpus", "1", updated_at=None)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return IndexedCorpus(
            data["corpus_id"], data["schema_version"],
            [IndexRecord(**record) for record in data.get("records", [])],
            data.get("source_fingerprints", {}),
            [SourceFileScope(**scope) for scope in data.get("source_manifest", [])],
            data.get("updated_at"),
        )

    def save(self, corpus: IndexedCorpus) -> None:
        """Atomically serialize a corpus and update its UTC timestamp.

        Args:
            corpus: Mutable corpus object to serialize. Its ``updated_at``
                property is set before writing.

        Returns:
            ``None``. JSON is written to a temporary sibling file and then
            replaces the destination.

        Raises:
            OSError: If directory creation, writing, or replacement fails.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        corpus.updated_at = datetime.now(timezone.utc).isoformat()
        fd, temporary = tempfile.mkstemp(prefix="corpus-", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(as_dict(corpus), handle, indent=2)
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def commit(self, corpus: IndexedCorpus) -> None:
        """Persist a committed corpus using the atomic ``save`` operation.

        Args:
            corpus: Corpus state to write.

        Returns:
            ``None``.
        """
        self.save(corpus)
