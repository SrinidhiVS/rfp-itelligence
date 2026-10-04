"""Persist and query Chroma vectors with manifest and crash recovery support."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

import chromadb
from filelock import FileLock, Timeout as FileLockTimeout

from .embedding_models import EmbeddingConfig, VectorIndexManifest, VectorRecord
from .identity import fingerprint, normalize_relative_path, scope_id
from .models import IndexRecord, SourceFileScope


class VectorIndexError(RuntimeError):
    """Raised for vector-index compatibility, persistence, or query failures."""

    pass


class VectorStore:
    """Manage a local Chroma collection and its source-scope manifest.

    Args:
        path: Directory used for the persistent Chroma collection, JSON
            manifest, transaction journal, and interprocess lock.

    Updates are scope-aware: unchanged source scopes retain their vectors,
    changed or removed scopes are reconciled, and a journal restores prior
    state after an interrupted mutation.
    """

    def __init__(self, path: Path):
        """Derive collection, manifest, journal, and lock paths from directory."""
        self.path = Path(path)
        self.manifest_path = self.path / "manifest.json"
        self.journal_path = self.path / "update-journal.json"
        self.lock_path = self.path.with_name(f".{self.path.name}.lock")

    @contextmanager
    def _open_collection(self) -> Iterator[object]:
        """Open the persistent collection while holding its file lock.

        Yields:
            Chroma collection named ``rfp_passages`` using cosine distance.

        Raises:
            VectorIndexError: If the lock times out or Chroma cannot be opened.
        """
        collection = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with FileLock(str(self.lock_path), timeout=30):
                self.path.mkdir(parents=True, exist_ok=True)
                client = chromadb.PersistentClient(path=str(self.path))
                collection = client.get_or_create_collection(
                    name="rfp_passages",
                    metadata={"hnsw:space": "cosine"},
                )
                self._recover_if_needed(collection)
                yield collection
        except FileLockTimeout as exc:
            raise VectorIndexError(f"timed out waiting for vector index lock: {exc}") from exc
        except VectorIndexError:
            raise
        except Exception as exc:
            raise VectorIndexError(f"could not open local Chroma index: {exc}") from exc

    def save(self, records: list[VectorRecord], config: EmbeddingConfig, scope_fingerprints: dict[str, str]) -> None:
        """Replace the complete vector collection and publish its manifest.

        Args:
            records: Vector records to store; all vectors must share one
                dimension.
            config: Provider, model, normalization, and expected dimension
                metadata for this index.
            scope_fingerprints: Mapping from source scope IDs to content hashes.

        Returns:
            ``None``. Existing entries are replaced and a UTC-updated manifest
            is written.

        Raises:
            VectorIndexError: If dimensions differ or the collection update
                fails.
        """
        dimension = len(records[0].vector) if records else (config.dimension or 0)
        dimensions = {len(record.vector) for record in records}
        if len(dimensions) > 1 or (config.dimension is not None and dimension not in {0, config.dimension}):
            raise VectorIndexError("vector index contains a dimension mismatch")
        manifest = VectorIndexManifest(
            collection_name="rfp_passages",
            provider=config.provider,
            model_name=config.model_name,
            dimension=dimension,
            normalize=config.normalize,
            scope_fingerprints=scope_fingerprints,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        try:
            with self._open_collection() as collection:
                existing_ids = collection.get(include=["metadatas"])["ids"]
                if existing_ids:
                    collection.delete(ids=existing_ids)
                if records:
                    collection.upsert(
                        ids=[record.record_id for record in records],
                        embeddings=[record.vector for record in records],
                        documents=[record.text for record in records],
                        metadatas=[self._metadata_for_record(record) for record in records],
                    )
                self._write_manifest(manifest)
        except Exception as exc:
            if isinstance(exc, VectorIndexError):
                raise
            raise VectorIndexError(f"vector index update failed: {exc}") from exc

    def build_from_records(self, records, provider) -> dict[str, int]:
        """Rebuild the vector index from all supplied records.

        Args:
            records: Iterable of current lexical ``IndexRecord`` objects.
            provider: Embedding provider exposing ``config`` and ``embed``.

        Returns:
            Integer counts for ``embedded`` vectors and ``skipped_empty``
            records.

        Raises:
            VectorIndexError: If the update reports a failure.
        """
        result = self.update_from_records(records, provider, full_rebuild=True)
        if result["failed"]:
            raise VectorIndexError(result["diagnostics"][0])
        return {"embedded": result["embedded"], "skipped_empty": result["skipped_empty"]}

    def update_from_records(
        self,
        records: Iterable[IndexRecord],
        provider,
        full_rebuild: bool = False,
        source_manifest: Iterable[SourceFileScope] | None = None,
    ) -> dict[str, object]:
        """Incrementally embed records and reconcile source scopes.

        Args:
            records: Iterable of lexical index records to synchronize.
            provider: Configured embedding provider.
            full_rebuild: If true, ignore existing fingerprints and re-embed
                all supplied scopes.
            source_manifest: Optional scopes with no records, allowing deleted
                or empty sources to be represented during reconciliation.

        Returns:
            Mapping with integer counts ``embedded``, ``skipped_empty``,
            ``unchanged``, ``replaced``, ``removed``, and ``failed``, plus a
            ``diagnostics`` string list. Operational errors are returned as a
            failed-update mapping rather than raised.
        """
        incoming = list(records)
        scopes: dict[str, list[IndexRecord]] = {}
        if source_manifest is not None:
            for source in source_manifest:
                scopes.setdefault(scope_id(source.bid_id, normalize_relative_path(source.relative_path)), [])
        for record in incoming:
            relative_path = record.source_locator.get("relative_path", record.source_file)
            canonical_scope = scope_id(record.bid_id, normalize_relative_path(relative_path))
            scopes.setdefault(canonical_scope, []).append(record)
        try:
            with self._open_collection() as collection:
                has_manifest = self.manifest_path.is_file()
                if has_manifest:
                    old_manifest = VectorIndexManifest(**json.loads(self.manifest_path.read_text(encoding="utf-8")))
                    if not full_rebuild and self._manifest_is_incompatible(old_manifest, provider.config):
                        return self._failed_update("local vector index is incompatible with the configured embedding model")
                    old_records = self._records_from_collection(
                        collection.get(include=["embeddings", "documents", "metadatas"])
                    )
                elif collection.count():
                    return self._failed_update("local vector index and manifest are incomplete")
                else:
                    old_manifest = VectorIndexManifest(
                        provider=provider.config.provider,
                        model_name=provider.config.model_name,
                        dimension=provider.config.dimension or 0,
                        normalize=provider.config.normalize,
                    )
                    old_records = []

                old_by_scope: dict[str, list[VectorRecord]] = {}
                for old_record in old_records:
                    old_by_scope.setdefault(old_record.scope_id, []).append(old_record)
                previous_scopes = old_manifest.scope_fingerprints
                old_fingerprints = previous_scopes if not full_rebuild else {}
                new_fingerprints: dict[str, str] = {}
                records_to_upsert: list[VectorRecord] = []
                records_to_keep: list[VectorRecord] = []
                affected_scopes: set[str] = set()
                embedded = skipped_empty = unchanged = replaced = 0

                for current_scope, scope_records in scopes.items():
                    usable = [record for record in scope_records if record.text and record.text.strip()]
                    skipped_empty += len(scope_records) - len(usable)
                    scope_fingerprint = fingerprint([
                        {
                            "record_id": record.record_id,
                            "content_fingerprint": record.content_fingerprint,
                            "text": record.text,
                            "bid_id": record.bid_id,
                            "source_file": record.source_file,
                            "page_number": record.page_number,
                            "section_title": record.section_title,
                            "content_kind": record.content_kind,
                            "doc_type": record.doc_type,
                            "addendum_number": record.addendum_number,
                            "document_date": record.document_date,
                            "source_locator": record.source_locator,
                            "status": record.status,
                        }
                        for record in usable
                    ])
                    new_fingerprints[current_scope] = scope_fingerprint

                    if not full_rebuild and old_fingerprints.get(current_scope) == scope_fingerprint:
                        unchanged += 1
                        records_to_keep.extend(old_by_scope.get(current_scope, []))
                        continue

                    affected_scopes.add(current_scope)
                    vectors = provider.embed([record.text for record in usable]) if usable else []
                    if len(vectors) != len(usable):
                        raise ValueError("embedding provider returned an unexpected vector count")
                    if any(provider.config.dimension is not None and len(vector) != provider.config.dimension for vector in vectors):
                        raise ValueError("embedding provider returned a vector with an incompatible dimension")
                    records_to_upsert.extend(
                        VectorRecord(
                            record_id=record.record_id,
                            vector=vector,
                            scope_id=current_scope,
                            content_fingerprint=record.content_fingerprint,
                            bid_id=record.bid_id,
                            source_file=record.source_file,
                            page_number=record.page_number,
                            source_locator=record.source_locator,
                            text=record.text,
                            doc_type=record.doc_type,
                            addendum_number=record.addendum_number,
                            document_date=record.document_date,
                            authority_status=record.status,
                            section_title=record.section_title,
                            content_kind=record.content_kind,
                        )
                        for record, vector in zip(usable, vectors)
                    )
                    embedded += len(vectors)
                    if current_scope in previous_scopes:
                        replaced += 1

                new_ids = {record.record_id for record in records_to_keep + records_to_upsert}
                existing_ids = set(collection.get(include=["metadatas"])["ids"])
                removed_ids = sorted(existing_ids - new_ids)
                affected_scopes.update(scope for scope in previous_scopes if scope not in new_fingerprints)
                prior_records = [
                    record
                    for record in old_records
                    if full_rebuild or record.scope_id in affected_scopes
                ]
                journal = {
                    "transaction_id": fingerprint([datetime.now(timezone.utc).isoformat(), sorted(new_ids)]),
                    "prior_manifest": old_manifest.__dict__ if has_manifest else None,
                    "prior_records": [record.__dict__ for record in prior_records],
                    "planned_upsert_ids": [record.record_id for record in records_to_upsert],
                    "planned_delete_ids": removed_ids,
                    "state": "prepared",
                }
                self._write_journal(journal)
                journal["state"] = "mutating"
                self._write_journal(journal)
                if records_to_upsert:
                    self._upsert_records(collection, records_to_upsert)
                if removed_ids:
                    collection.delete(ids=removed_ids)
                manifest = VectorIndexManifest(
                    provider=provider.config.provider,
                    model_name=provider.config.model_name,
                    dimension=(len(records_to_upsert[0].vector) if records_to_upsert else old_manifest.dimension or provider.config.dimension or 0),
                    normalize=provider.config.normalize,
                    scope_fingerprints=new_fingerprints,
                    updated_at=datetime.now(timezone.utc).isoformat(),
                )
                self._write_manifest(manifest)
                journal["state"] = "manifest-published"
                self._write_journal(journal)
                self.journal_path.unlink(missing_ok=True)
                removed_scopes = sum(scope not in new_fingerprints for scope in previous_scopes)
                return {
                    "embedded": embedded,
                    "skipped_empty": skipped_empty,
                    "unchanged": unchanged,
                    "replaced": replaced,
                    "removed": removed_scopes,
                    "failed": 0,
                    "diagnostics": [],
                }
        except Exception as exc:
            return self._failed_update(str(exc))

    def load(self, config: EmbeddingConfig | None = None) -> tuple[list[VectorRecord], VectorIndexManifest]:
        """Load stored vectors and optionally verify embedding compatibility.

        Args:
            config: If provided, expected provider/model/normalization and
                optional dimension used to validate the manifest.

        Returns:
            Pair of reconstructed vector records and their manifest.

        Raises:
            VectorIndexError: If the index or manifest is missing, corrupt,
                incompatible, or contains vectors of the wrong dimension.
        """
        if not self.manifest_path.is_file():
            raise VectorIndexError("local vector index or manifest is missing")
        try:
            manifest = VectorIndexManifest(**json.loads(self.manifest_path.read_text(encoding="utf-8")))
            with self._open_collection() as collection:
                stored = collection.get(include=["embeddings", "documents", "metadatas"])
            records = self._records_from_collection(stored)
        except Exception as exc:
            if isinstance(exc, VectorIndexError):
                raise
            raise VectorIndexError(f"local vector index is corrupt: {exc}") from exc
        if config and self._manifest_is_incompatible(manifest, config):
            raise VectorIndexError("local vector index is incompatible with the configured embedding model")
        if any(len(record.vector) != manifest.dimension for record in records):
            raise VectorIndexError("local vector index contains a dimension mismatch")
        return records, manifest

    def query(
        self,
        query_vector: list[float],
        top_k: int,
        filters: dict,
        config: EmbeddingConfig,
    ) -> list[tuple[VectorRecord, float]]:
        """Return nearest records as ``(record, cosine_similarity)`` pairs.

        Args:
            query_vector: Query embedding with the manifest's vector dimension.
            top_k: Maximum number of nearest records; non-positive values
                return an empty list.
            filters: Optional ``bid_id``, ``doc_type``, and
                ``addendum_number`` metadata filters.
            config: Embedding configuration checked against the index manifest.

        Returns:
            Nearest vector records paired with similarity scores computed as
            ``1 - Chroma cosine distance``.

        Raises:
            VectorIndexError: If the index is missing, incompatible, corrupt,
                or the query vector dimension differs from the index.
        """
        if not self.manifest_path.is_file():
            raise VectorIndexError("local vector index or manifest is missing")
        try:
            with self._open_collection() as collection:
                manifest = VectorIndexManifest(**json.loads(self.manifest_path.read_text(encoding="utf-8")))
                if self._manifest_is_incompatible(manifest, config):
                    raise VectorIndexError("local vector index is incompatible with the configured embedding model")
                if len(query_vector) != manifest.dimension:
                    raise VectorIndexError("query vector dimension does not match the local vector index")
                count = collection.count()
                if top_k <= 0 or count == 0:
                    return []
                matches = collection.query(
                    query_embeddings=[query_vector],
                    n_results=min(top_k, count),
                    where=self._where_filter(filters),
                    include=["embeddings", "documents", "metadatas", "distances"],
                )
            identifiers = matches["ids"][0]
            records = self._records_from_collection(
                {
                    "ids": identifiers,
                    "embeddings": matches["embeddings"][0],
                    "documents": matches["documents"][0],
                    "metadatas": matches["metadatas"][0],
                }
            )
            return [
                (record, 1.0 - float(distance))
                for record, distance in zip(records, matches["distances"][0])
            ]
        except Exception as exc:
            if isinstance(exc, VectorIndexError):
                raise
            raise VectorIndexError(f"local Chroma query failed: {exc}") from exc

    @staticmethod
    def _where_filter(filters: dict) -> dict | None:
        """Translate public search filters into Chroma's metadata predicate.

        Args:
            filters: Mapping with optional ``bid_id`` (string or collection),
                ``doc_type``, and ``addendum_number`` entries.

        Returns:
            ``None`` when no filters are present, otherwise one Chroma clause
            or an ``$and`` mapping containing all clauses.
        """
        clauses = []
        bid_filter = filters.get("bid_id")
        if bid_filter:
            if isinstance(bid_filter, (list, tuple, set)):
                values = sorted(bid_filter) if isinstance(bid_filter, set) else list(bid_filter)
                clauses.append({"bid_id": {"$in": values}})
            else:
                clauses.append({"bid_id": bid_filter})
        if filters.get("doc_type"):
            clauses.append({"doc_type": filters["doc_type"]})
        if filters.get("addendum_number") is not None:
            clauses.append({"addendum_number": int(filters["addendum_number"])})
        if not clauses:
            return None
        return clauses[0] if len(clauses) == 1 else {"$and": clauses}

    @staticmethod
    def _metadata_for_record(record: VectorRecord) -> dict[str, str | int | float | bool]:
        """Serialize vector record citation and authority fields to metadata.

        Args:
            record: Vector record to store.

        Returns:
            Chroma-compatible scalar metadata mapping. ``source_locator`` is
            JSON-encoded; optional ``None`` values are omitted.
        """
        metadata: dict[str, str | int | float | bool] = {
            "scope_id": record.scope_id,
            "content_fingerprint": record.content_fingerprint,
            "bid_id": record.bid_id,
            "source_file": record.source_file,
            "source_locator": json.dumps(record.source_locator, ensure_ascii=False),
            "authority_status": record.authority_status,
        }
        optional = {
            "page_number": record.page_number,
            "doc_type": record.doc_type,
            "addendum_number": record.addendum_number,
            "document_date": record.document_date,
            "superseded_by": record.superseded_by,
            "section_title": record.section_title,
            "content_kind": record.content_kind,
        }
        metadata.update({key: value for key, value in optional.items() if value is not None})
        return metadata

    @staticmethod
    def _records_from_collection(stored: dict) -> list[VectorRecord]:
        """Reconstruct typed vector records from Chroma collection columns.

        Args:
            stored: Chroma ``get``-style mapping with IDs, embeddings,
                documents, and metadata arrays.

        Returns:
            Vector records with float vectors and decoded source locators.
        """
        vectors = stored["embeddings"]
        if hasattr(vectors, "tolist"):
            vectors = vectors.tolist()
        records = []
        for record_id, vector, text, metadata in zip(
            stored["ids"], vectors, stored["documents"], stored["metadatas"]
        ):
            decoded = dict(metadata or {})
            locator = json.loads(decoded.pop("source_locator", "{}"))
            records.append(
                VectorRecord(
                    record_id=record_id,
                    vector=[float(value) for value in vector],
                    scope_id=decoded.pop("scope_id"),
                    content_fingerprint=decoded.pop("content_fingerprint"),
                    bid_id=decoded.pop("bid_id"),
                    source_file=decoded.pop("source_file"),
                    page_number=decoded.pop("page_number", None),
                    source_locator=locator,
                    text=text or "",
                    doc_type=decoded.pop("doc_type", None),
                    addendum_number=decoded.pop("addendum_number", None),
                    document_date=decoded.pop("document_date", None),
                    authority_status=decoded.pop("authority_status", "unknown"),
                    superseded_by=decoded.pop("superseded_by", None),
                    section_title=decoded.pop("section_title", None),
                    content_kind=decoded.pop("content_kind", None),
                )
            )
        return records

    def _write_manifest(self, manifest: VectorIndexManifest) -> None:
        """Atomically write the JSON index manifest."""
        self.path.mkdir(parents=True, exist_ok=True)
        self._atomic_write(self.manifest_path, json.dumps(manifest.__dict__, indent=2))

    def _write_journal(self, journal: dict) -> None:
        """Atomically write the JSON transaction recovery journal."""
        self.path.mkdir(parents=True, exist_ok=True)
        self._atomic_write(self.journal_path, json.dumps(journal, indent=2))

    def _recover_if_needed(self, collection) -> None:
        """Restore pre-update records unless the manifest was already published.

        Args:
            collection: Open Chroma collection to reconcile with the journal.

        Returns:
            ``None``. The journal is deleted after recovery or confirmation of
            a completed manifest publication.
        """
        if not self.journal_path.is_file():
            return
        journal = json.loads(self.journal_path.read_text(encoding="utf-8"))
        if journal.get("state") != "manifest-published":
            record_ids = set(journal.get("planned_upsert_ids", [])) | set(journal.get("planned_delete_ids", []))
            if record_ids:
                collection.delete(ids=sorted(record_ids))
            prior_records = [VectorRecord(**item) for item in journal.get("prior_records", [])]
            if prior_records:
                self._upsert_records(collection, prior_records)
            prior_manifest = journal.get("prior_manifest")
            if prior_manifest is None:
                self.manifest_path.unlink(missing_ok=True)
            else:
                self._atomic_write(self.manifest_path, json.dumps(prior_manifest, indent=2))
        self.journal_path.unlink(missing_ok=True)

    def _upsert_records(self, collection, records: list[VectorRecord]) -> None:
        """Upsert vector records and their derived metadata into Chroma.

        Args:
            collection: Open Chroma collection.
            records: Records whose IDs, embeddings, text, and metadata are
                written together.

        Returns:
            ``None``.
        """
        collection.upsert(
            ids=[record.record_id for record in records],
            embeddings=[record.vector for record in records],
            documents=[record.text for record in records],
            metadatas=[self._metadata_for_record(record) for record in records],
        )

    @staticmethod
    def _manifest_is_incompatible(manifest: VectorIndexManifest, config: EmbeddingConfig) -> bool:
        """Compare persisted manifest model settings with requested settings.

        Args:
            manifest: Settings recorded when vectors were created.
            config: Settings requested for the current operation.

        Returns:
            ``True`` if provider, model, normalization, or a configured
            dimension differs.
        """
        return (
            manifest.provider != config.provider
            or manifest.model_name != config.model_name
            or manifest.normalize != config.normalize
            or (config.dimension is not None and manifest.dimension != config.dimension)
        )

    def _atomic_write(self, path: Path, content: str) -> None:
        """Stage text in the destination directory and atomically publish it."""
        temporary = self._stage_write(path, content)
        try:
            self._publish_staged(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _stage_write(self, path: Path, content: str) -> str:
        """Write content to a temporary sibling file and return its path."""
        fd, temporary = tempfile.mkstemp(prefix="vector-index-", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
        except Exception:
            if os.path.exists(temporary):
                os.unlink(temporary)
            raise
        return temporary

    @staticmethod
    def _publish_staged(temporary: str, path: Path) -> None:
        """Replace the destination file with a staged temporary file."""
        os.replace(temporary, path)

    def _restore_file(self, path: Path, content: str | None) -> None:
        """Restore file content, deleting the path when prior content was absent."""
        if content is None:
            path.unlink(missing_ok=True)
        else:
            self._atomic_write(path, content)

    @staticmethod
    def _failed_update(message: str, skipped_empty: int = 0) -> dict[str, object]:
        """Build the standard failed-update count and diagnostic mapping."""
        return {
            "embedded": 0,
            "skipped_empty": skipped_empty,
            "unchanged": 0,
            "replaced": 0,
            "removed": 0,
            "failed": 1,
            "diagnostics": [message],
        }
