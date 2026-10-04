"""Load API connection, polling, timeout, and default bid settings."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class FrontendConfig:
    """Immutable Streamlit client configuration populated from environment.

    Timeout fields are seconds; ``api_url`` is normalized without a trailing
    slash; and ``bid_ids`` is a tuple parsed from comma-separated
    ``RFP_BID_IDS``.
    """

    api_url: str = "http://127.0.0.1:8000"
    timeout_seconds: float = 60.0
    job_request_timeout_seconds: float = 15.0
    job_poll_interval_seconds: float = 1.0
    job_max_wait_seconds: float = 1800.0
    bid_ids: tuple[str, ...] = ("Bid1", "Bid2")

    @classmethod
    def from_env(cls) -> "FrontendConfig":
        """Parse frontend settings from supported ``RFP_*`` environment keys."""
        raw_bids = os.getenv("RFP_BID_IDS", "Bid1,Bid2")
        bid_ids = tuple(item.strip() for item in raw_bids.split(",") if item.strip())
        return cls(
            api_url=os.getenv("RFP_API_URL", "http://127.0.0.1:8000").rstrip("/"),
            timeout_seconds=float(os.getenv("RFP_FRONTEND_TIMEOUT", "60")),
            job_request_timeout_seconds=float(os.getenv("RFP_JOB_REQUEST_TIMEOUT", "15")),
            job_poll_interval_seconds=float(os.getenv("RFP_JOB_POLL_INTERVAL", "1")),
            job_max_wait_seconds=float(os.getenv("RFP_JOB_MAX_WAIT", "1800")),
            bid_ids=bid_ids or ("Bid1", "Bid2"),
        )
