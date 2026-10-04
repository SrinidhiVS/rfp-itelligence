# Ingestion Design

## Boundaries

`IngestionPipeline` owns one bid folder per run. Discovery and classification create a complete
file inventory before parser adapters run. HTML and PDF adapters emit the same page/table model;
normalization and chunking operate on that shared model.

## Status semantics

- `parsed`: source content was extracted without completeness-affecting diagnostics.
- `partial`: some content or metadata is uncertain or incomplete.
- `failed`: parsing raised an error for the source.
- `unsupported`: the source format is retained in the inventory but not parsed.
- Folder status rolls these values up to `complete`, `incomplete`, `failed`, or `empty`.

## Provenance

Identifiers are deterministic hashes of bid, relative path, page/location, table order, and chunk
content. Every chunk retains a relative source path and page or section context when available.
Missing dates and addendum numbers remain null rather than being inferred.

## Tables and OCR

HTML tables and PDF tables are extracted separately from plain text and may also become table
chunks. Table extraction failures are visible diagnostics. Image-only pages are represented as
empty or partial source pages; OCR is intentionally excluded from the required implementation.
