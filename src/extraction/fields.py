"""Expose canonical field names, aliases, and collection-field membership."""

from __future__ import annotations

from src.field_registry import CANONICAL_FIELD_DEFINITIONS


CANONICAL_FIELDS = tuple(
    definition.canonical_name
    for definition in CANONICAL_FIELD_DEFINITIONS
    if definition.canonical_name is not None
)
FIELD_TERMS = {
    definition.canonical_name: definition.aliases
    for definition in CANONICAL_FIELD_DEFINITIONS
    if definition.canonical_name is not None
}
COLLECTION_FIELDS = frozenset(
    definition.canonical_name
    for definition in CANONICAL_FIELD_DEFINITIONS
    if definition.canonical_name is not None and definition.is_collection
)
