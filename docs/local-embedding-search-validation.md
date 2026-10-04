# Local Embedding Search Validation

The local embedding feature requires a completed local Sentence Transformers installation before
semantic indexing. Deterministic provider tests remain available without model downloads.

Validation covers provider compatibility, vector metadata, bid/document/addendum filters, keyword
fallback, incremental scope fingerprints, semantic/hybrid configuration, citations, and Recall@k/MRR.
