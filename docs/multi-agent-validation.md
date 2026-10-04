# Multi-Agent Validation

Run the focused workflow checks with:

```text
python -m pytest -q tests/contract tests/unit tests/integration
```

The acceptance suite must verify citation coverage across the Bid1, Bid2, and unseen-bid fixtures,
at least 10 deterministic parallel field-group executions, bounded retries, structured failure
responses, stable FastAPI schemas, and all seven trace stages. Use `traces/example-extraction.json`
for offline trace review.
