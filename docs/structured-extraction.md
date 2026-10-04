# Structured Extraction

The extraction package produces one schema-valid JSON record per bid folder. It preserves the
canonical twenty fields, source citations, confidence scores, notes, addendum changes, validation
counts, and processing diagnostics.

Missing or unsupported fields are represented as `null` with empty citations, confidence `0.0`,
and an explicit not-found or review-required note. Addendum values are selected by addendum number
or effective date, then source authority; unresolved conflicts remain review-required.

Run extraction with:

```powershell
python -m src.extraction.cli extract --input Initial_docs/Bid1 --output output/bid-records
```

The output is written to `output/bid-records/<bid-id>/structured-record.json`.
