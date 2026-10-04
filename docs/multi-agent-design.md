# Multi-Agent Analysis

The workflow in `src/agents/graph.py` uses explicit LangGraph nodes for Planner, Ingestion,
Retrieval, Extraction, Reconciliation, Validation, and Report. Nodes exchange typed Pydantic state
and message envelopes. Retrieval returns ranked evidence and citations from the feature-002 search
engine; whole source documents are never passed as model context.

FastAPI exposes `POST /v1/analysis/extract` and `POST /v1/analysis/qa`. Every response contains a
stable status, diagnostics, trace reference, and `EvaluationReport`. Missing evidence produces
`Not found in documents` or an unavailable field instead of an inferred value.

Provider settings come from environment variables. Tests inject deterministic search/model/trace
providers, so credentials are not required for local validation. Trace summaries omit source content
and secrets; LangSmith-compatible tracing can be enabled through the configured project settings.

Set `RFP_MODEL_PROVIDER=ollama`, `RFP_OLLAMA_MODEL=qwen2.5:3b`, and
`RFP_OLLAMA_BASE_URL=http://localhost:11434/v1` to use a local Ollama model for structured field
extraction and final QA answer prose. QA report prose is generated only after deterministic evidence
analysis has produced non-disputed claims; citations, claim records, and not-found decisions remain
unchanged. If model report generation fails, the deterministic answer is returned. The default
`RFP_MODEL_PROVIDER=auto` retains OpenAI-if-configured and deterministic-offline behavior.
