"""Define extraction/report provider contracts and configured model adapters."""

from __future__ import annotations

import json
from typing import Any, Protocol

from .settings import Settings
from .state import ExtractionResult, ModelUsage


class ModelProvider(Protocol):
    """Interface for field extraction and evidence-bounded report generation."""

    def extract_fields(self, evidence: list[dict[str, Any]], field_names: list[str]) -> ExtractionResult:
        """Return JSON-compatible proposals for the requested evidence-backed fields."""
        ...

    def generate_report(self, question: str, claims: list[dict[str, Any]], fallback_answer: str) -> ExtractionResult:
        """Return concise answer prose constrained to established claims."""
        ...


class DeterministicModelProvider:
    """Offline no-op provider for tests and unconfigured environments."""

    def extract_fields(self, evidence: list[dict[str, Any]], field_names: list[str]) -> ExtractionResult:
        """Return no model proposals while allowing deterministic extraction.

        Args:
            evidence: Retrieved source mappings (unused by this provider).
            field_names: Requested field names (unused by this provider).

        Returns:
            Empty ``ExtractionResult`` with usage marked unavailable.
        """
        return ExtractionResult()

    def generate_report(self, question: str, claims: list[dict[str, Any]], fallback_answer: str) -> ExtractionResult:
        """Return the already synthesized answer without external model calls."""
        return ExtractionResult(values={"answer": fallback_answer})


class OpenAIModelProvider:
    """Use OpenAI-compatible chat completions for extraction and report prose."""

    def __init__(self, settings: Settings):
        """Initialize an OpenAI client from required settings credentials."""
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        from openai import OpenAI

        self.client = OpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_model
        self.provider_name = "openai"

    def _usage(self, response) -> ModelUsage:
        """Normalize response token counts into ``ModelUsage``."""
        usage = response.usage
        counts = {
            "input_tokens": getattr(usage, "prompt_tokens", None),
            "output_tokens": getattr(usage, "completion_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
        }
        return ModelUsage(
            provider=self.provider_name,
            model=self.model,
            availability="reported" if any(value is not None for value in counts.values()) else "unavailable",
            **counts,
        )

    def extract_fields(self, evidence: list[dict[str, Any]], field_names: list[str]) -> ExtractionResult:
        """Request JSON field proposals constrained to supplied evidence.

        Args:
            evidence: Ranked evidence mappings with nested record data.
            field_names: Field names the model may propose.

        Returns:
            ``ExtractionResult`` whose values map field names to JSON values
            and whose usage contains provider/model token counts.
        """
        evidence_payload = [
            {"id": item.get("record_id"), "bid_id": item["record"]["bid_id"], "file": item["record"]["source_file"], "page": item["record"].get("page_number"), "text": item["record"]["text"][:2000]}
            for item in evidence
        ]
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "Extract only values supported by the supplied evidence. Use null when unsupported. Return JSON keyed by field name."},
                {"role": "user", "content": json.dumps({"fields": field_names, "evidence": evidence_payload})},
            ],
        )
        return ExtractionResult(
            values=json.loads(response.choices[0].message.content or "{}"),
            usage=self._usage(response),
        )

    def generate_report(self, question: str, claims: list[dict[str, Any]], fallback_answer: str) -> ExtractionResult:
        """Generate concise prose from established claims without adding facts."""
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "Write a concise answer using only the supplied established claims. Do not add facts, values, dates, or qualifications. Return a JSON object with an 'answer' string."},
                {"role": "user", "content": json.dumps({"question": question, "claims": [claim["text"] for claim in claims]})},
            ],
        )
        values = json.loads(response.choices[0].message.content or "{}")
        answer = values.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("model returned no report answer")
        return ExtractionResult(values={"answer": answer.strip()}, usage=self._usage(response))


class OllamaModelProvider(OpenAIModelProvider):
    """Connect to an Ollama server exposing the OpenAI-compatible API."""

    def __init__(self, settings: Settings):
        """Initialize the OpenAI client against the configured Ollama URL."""
        from openai import OpenAI

        base_url = settings.ollama_base_url.rstrip("/")
        if not base_url.endswith("/v1"):
            base_url = f"{base_url}/v1"
        self.client = OpenAI(base_url=base_url, api_key="ollama")
        self.model = settings.ollama_model
        self.provider_name = "ollama"


def configured_provider(settings: Settings | None = None) -> ModelProvider:
    """Choose deterministic, OpenAI, or Ollama provider from settings.

    Args:
        settings: Provider settings; loaded from environment when omitted.

    Returns:
        Provider implementing extraction and report generation.

    Raises:
        ValueError: If configured provider name is unsupported.
        RuntimeError: If explicitly selected OpenAI lacks its API key.
    """
    settings = settings or Settings.from_env()
    if settings.model_provider == "ollama":
        return OllamaModelProvider(settings)
    if settings.model_provider == "openai":
        return OpenAIModelProvider(settings)
    if settings.model_provider != "auto":
        raise ValueError("RFP_MODEL_PROVIDER must be 'auto', 'openai', or 'ollama'")
    return OpenAIModelProvider(settings) if settings.openai_api_key else DeterministicModelProvider()
