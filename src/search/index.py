"""Build and incrementally maintain the persisted search corpus index.

``IndexService`` validates incoming bid-scoped chunks, tracks source-file
fingerprints, preserves unchanged records, and commits updates through a
``CorpusStore``. Its public methods return current typed records or
JSON-compatible corpus summaries.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .contracts import validate_index_request
from .identity import fingerprint, normalize_relative_path, record_id, scope_id
from .models import IndexedCorpus, IndexRecord, SourceFileScope, as_dict
from .observability import event
from .storage import CorpusStore


class IndexService:
    """Coordinate validated index updates and corpus reads.

    Args:
        store: Persistence adapter used to load and commit ``IndexedCorpus``
            instances.
    """

    def __init__(self, store: CorpusStore):
        """Bind the service to its lexical corpus persistence adapter."""
        self.store = store

    def update(self, request: dict[str, Any], full_rebuild: bool = False) -> dict[str, Any]:
        """Apply a bid index request and persist the resulting corpus.

        Args:
            request: Mapping validated by ``validate_index_request``. It
                contains a ``bid_id`` and optional ``chunks``,
                ``source_manifest``, and ``preserve_scopes`` entries.
            full_rebuild: If true, discard the existing corpus before adding
                the request's sources; otherwise update only the requested bid.

        Returns:
            Count summary with integer keys ``indexed``, ``skipped``,
            ``replaced``, ``removed``, ``failed``, ``unchanged``, and
            ``source_scopes``. ``unchanged`` mirrors ``skipped``.

        Raises:
            Exception: Propagates validation or persistence failures. A failed
                commit triggers restoration of the previously loaded corpus.
        """
        validate_index_request(request)
        current = self.store.load()
        before = deepcopy(current)
        old_records = list(current.records)
        preserve_scopes = set(request.get("preserve_scopes", []))
        incoming_scopes: dict[str, tuple[str, str, list[dict[str, Any]]]] = {}
        for manifest_item in request.get("source_manifest", []):
            path = normalize_relative_path(manifest_item.get("relative_path", "unknown"))
            scope = scope_id(request["bid_id"], path)
            incoming_scopes.setdefault(scope, (request["bid_id"], path, []))
        for chunk in request.get("chunks", []):
            path = normalize_relative_path(chunk.get("source_locator", {}).get("relative_path", chunk.get("source_file", "unknown")))
            scope = scope_id(request["bid_id"], path)
            incoming_scopes.setdefault(scope, (request["bid_id"], path, []))[2].append(chunk)
        existing_scopes = {scope.scope_id: scope for scope in current.source_manifest}
        if full_rebuild:
            current.records = []
            current.source_fingerprints = {}
            current.source_manifest = []
            existing_scopes = {}
        else:
            current.records = [record for record in current.records if record.bid_id != request["bid_id"] and record.status == "current"]
            current.source_manifest = [scope for scope in current.source_manifest if scope.bid_id != request["bid_id"]]
        indexed = skipped = replaced = removed = failed = 0
        new_manifest: list[SourceFileScope] = list(current.source_manifest)
        new_records: list[IndexRecord] = list(current.records)
        for scope, (bid_id, path, chunks) in incoming_scopes.items():
            source_fingerprint = fingerprint(chunks)
            old_scope = existing_scopes.get(scope)
            if old_scope and old_scope.content_fingerprint == source_fingerprint and not full_rebuild:
                skipped += 1
                new_manifest.append(SourceFileScope(bid_id, path, scope, source_fingerprint, "unchanged"))
                new_records.extend(record for record in old_records if record.scope_id == scope and record.status == "current")
                continue
            records = []
            try:
                for chunk in chunks:
                    chunk_fingerprint = fingerprint([scope, chunk.get("chunk_id"), chunk.get("text"), chunk])
                    records.append(IndexRecord(
                        record_id=record_id(scope, chunk.get("chunk_id", ""), chunk_fingerprint),
                        chunk_id=chunk.get("chunk_id", ""), scope_id=scope,
                        content_fingerprint=chunk_fingerprint, text=chunk.get("text", ""),
                        bid_id=bid_id, source_file=chunk.get("source_file", path),
                        page_number=chunk.get("page_number"), section_title=chunk.get("section_title"),
                        doc_type=chunk.get("doc_type"), addendum_number=chunk.get("addendum_number"),
                        document_date=chunk.get("document_date"), source_locator=chunk.get("source_locator", {}),
                        diagnostic_ids=chunk.get("diagnostic_ids", []), content_kind=chunk.get("content_kind"),
                    ))
                if old_scope and not full_rebuild:
                    replaced += 1
                else:
                    indexed += 1
                new_records.extend(records)
                new_manifest.append(SourceFileScope(bid_id, path, scope, source_fingerprint, "changed" if old_scope else "new"))
            except Exception:
                failed += 1
                if old_scope:
                    new_manifest.append(old_scope)
                    new_records.extend(record for record in old_records if record.scope_id == scope and record.status == "current")
        if not full_rebuild:
            for old_scope in existing_scopes.values():
                if old_scope.bid_id == request["bid_id"] and old_scope.scope_id not in incoming_scopes:
                    if old_scope.scope_id in preserve_scopes:
                        new_manifest.append(old_scope)
                        new_records.extend(record for record in old_records if record.scope_id == old_scope.scope_id and record.status == "current")
                    else:
                        removed += 1
        current.records = new_records
        current.source_manifest = new_manifest
        current.source_fingerprints = {item.scope_id: item.content_fingerprint for item in new_manifest}
        try:
            self.store.commit(current)
        except Exception:
            self.store.commit(before)
            raise
        event("index_updated", indexed=indexed, skipped=skipped, replaced=replaced, removed=removed, failed=failed)
        return {"indexed": indexed, "skipped": skipped, "replaced": replaced, "removed": removed, "failed": failed, "unchanged": skipped, "source_scopes": len(new_manifest)}

    def records(self) -> list[IndexRecord]:
        """Return all currently active records in the persisted corpus.

        Returns:
            A list of ``IndexRecord`` objects whose status is ``"current"``.
        """
        return [record for record in self.store.load().records if record.status == "current"]

    def report(self) -> dict[str, Any]:
        """Return the complete persisted corpus as nested dictionaries.

        Returns:
            A JSON-compatible mapping containing corpus metadata, records,
            source fingerprints, and source manifest entries.
        """
        return as_dict(self.store.load())
