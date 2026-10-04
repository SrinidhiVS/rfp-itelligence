# Search Validation

Validated with the combined ingestion and search test suite. The search unit tests cover stable
source scopes, idempotent indexing, bid isolation, changed-file replacement, query expansion,
filters, explicit not-found answers, addendum ordering, and ranking metrics.

The public API smoke path processes Bid1 and Bid2, indexes both reports into one corpus, searches
for `deadline`, and runs a cited QA query. The index is persisted under the path selected by
`RFP_INDEX_PATH` and can be rebuilt explicitly with the `rebuild` command.

The evaluation fixture contains 21 source-verified Bid1 and Bid2 cases spanning exact values,
concepts, deadlines, addendums, filters, comparisons, and not-found behavior. Its 22 expected
record IDs are already populated, each paired with a short quoted passage checked against the
indexed corpus. The measured semantic-only and hybrid comparison, run context, and reproduction
command are in the [README retrieval evaluation results](../README.md#retrieval-evaluation-results).