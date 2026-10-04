# Structured Extraction Validation

The feature task plan covers contract, unit, integration, addendum, missing-field, unseen-bid,
source-failure, citation-quality, and schema-matrix checks.

Run the complete suite with:

```powershell
python -m pytest -q
```

Validate the CLI and inspect `output/bid-records/<bid-id>/structured-record.json` for all twenty
fields, citations, confidence values, notes, addendum changes, validation counts, and diagnostics.

## Requirement-to-Test Matrix

| Requirement range | Validation coverage |
|---|---|
| FR-001 through FR-006 | `tests/contract/test_extraction_models.py`, `tests/unit/test_identity.py`, `tests/unit/test_extractor.py`, `tests/unit/test_missing_fields.py` |
| FR-007 through FR-012 | `tests/unit/test_reconciliation.py`, `tests/unit/test_reconciliation_conflicts.py`, `tests/integration/test_addendum_extraction.py` |
| FR-013 through FR-016 | `tests/unit/test_source_diagnostics.py`, `tests/unit/test_unsupported_values.py`, `tests/integration/test_partial_source_failure.py`, `tests/integration/test_unseen_bid_extraction.py` |
| FR-017 through FR-020 | `tests/unit/test_validation.py`, `tests/contract/test_extraction_serialization.py`, `tests/integration/test_scope_validation.py` |
| SC-001 through SC-004 | `tests/integration/test_extraction_acceptance.py`, `tests/integration/test_missing_and_failure_acceptance.py` |
| SC-005 through SC-008 | `tests/integration/test_addendum_extraction.py`, `tests/integration/test_source_failure_fixture.py`, `tests/integration/test_citation_quality.py` |
| SC-009 through SC-012 | `tests/integration/test_schema_matrix.py`, `tests/integration/test_full_schema_acceptance.py`, `tests/integration/test_requirement_matrix.py` |
| US1/AC1 through US1/AC3 | `tests/integration/test_extraction_acceptance.py`, `tests/unit/test_extractor.py` |
| US2/AC1 through US2/AC3 | `tests/unit/test_reconciliation.py`, `tests/unit/test_reconciliation_conflicts.py`, `tests/integration/test_addendum_extraction.py` |
| US3/AC1 through US3/AC4 | `tests/unit/test_missing_fields.py`, `tests/integration/test_unseen_bid_extraction.py`, `tests/integration/test_source_failure_fixture.py` |

## CLI Run Record

On 2026-10-01, the documented command was run for Bid1, Bid2, and `Initial_docs/UnseenBid`.
All three commands exited successfully and produced parseable records under
`output/bid-records/`. Each record contained `bid_id`, `fields`, `addendum_changes`,
`validation`, and `diagnostics`; each nested `fields` object contained all twenty canonical fields.
