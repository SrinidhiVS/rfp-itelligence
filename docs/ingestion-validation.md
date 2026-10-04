# Ingestion Validation Results

Validated on 2026-10-01.

- Automated suite: 7 passed, 0 failed.
- Bid1: incomplete because five empty pages were diagnosed; 4 files, 69 pages, 81 tables,
  145 chunks, 5 diagnostics.
- Bid2: complete; 5 files, 12 pages, 5 tables, 17 chunks, 0 diagnostics.
- Malformed fixture: valid HTML remains processable while malformed PDF and unsupported text are
  retained in the inventory with incomplete status and diagnostics.
- Determinism: repeated Bid1 processing produced matching document, chunk, and normalized-page
  identifiers/content.

The full acceptance corpus metrics for text-retention and table-retention percentages remain a
follow-up once the larger labeled fixture corpus is assembled.
