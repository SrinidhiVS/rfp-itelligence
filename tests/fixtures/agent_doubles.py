from __future__ import annotations

from typing import Any


class DeterministicSearch:
    def __init__(self, results: list[dict[str, Any]] | None = None):
        self.results = results or []

    def search(self, query, configuration="hybrid"):
        return {"results": self.results[:query.top_k], "diagnostics": [], "query_variants": {"variants": [query.text]}}


class DeterministicModel:
    def __init__(self, response: dict[str, Any] | None = None):
        self.response = response or {}

    def invoke(self, _messages):
        return self.response


class DeterministicTraceProvider:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.events = []

    def record(self, event):
        if self.fail:
            raise RuntimeError("trace provider unavailable")
        self.events.append(event)
