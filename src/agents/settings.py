"""Load immutable model, tracing, retry, index, and trace-path settings."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


@dataclass(frozen=True)
class Settings:
    """Immutable runtime configuration; values can be populated from environment.

    Provider/model fields select OpenAI or Ollama; trace fields configure
    LangSmith and local trace persistence; retry count limits validation loops;
    and index/trace paths locate local runtime data.
    """

    model_provider: str = "auto"
    openai_model: str = "gpt-4o-mini"
    openai_api_key: str | None = None
    ollama_model: str = "qwen2.5:3b"
    ollama_base_url: str = "http://localhost:11434/v1"
    langsmith_api_key: str | None = None
    langsmith_project: str = "rfp-multi-agent-analysis"
    max_retries: int = 2
    trace_enabled: bool = True
    index_path: str = "output/search-index.json"
    trace_path: str = "traces/runtime-trace.json"

    @classmethod
    def from_env(cls) -> "Settings":
        """Load the workspace .env file and overlay supported environment keys.

        Returns:
            Validated ``Settings`` with defaults for absent variables and a
            non-negative retry limit.
        """
        load_dotenv(dotenv_path=ENV_FILE, override=False)
        return cls(
            model_provider=os.getenv("RFP_MODEL_PROVIDER", "auto").lower(),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            ollama_model=os.getenv("RFP_OLLAMA_MODEL", "qwen2.5:3b"),
            ollama_base_url=os.getenv("RFP_OLLAMA_BASE_URL", "http://localhost:11434/v1"),
            langsmith_api_key=os.getenv("LANGSMITH_API_KEY"),
            langsmith_project=os.getenv("LANGSMITH_PROJECT", "rfp-multi-agent-analysis"),
            max_retries=max(0, int(os.getenv("RFP_MAX_RETRIES", "2"))),
            trace_enabled=os.getenv("RFP_TRACE", "true").lower() not in {"0", "false", "no"},
            index_path=os.getenv("RFP_INDEX_PATH", "output/search-index.json"),
            trace_path=os.getenv("RFP_TRACE_PATH", "traces/runtime-trace.json"),
        )

    def require_model(self) -> None:
        """Require an OpenAI API key for operations that need OpenAI access."""
        if not self.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")
