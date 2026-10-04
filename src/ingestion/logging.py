"""Configure and emit structured events for ingestion processing."""

from __future__ import annotations

import logging


LOGGER = logging.getLogger("rfp_ingestion")


def configure_logging(verbose: bool = False) -> None:
    """Configure root logging at INFO or DEBUG level.

    Args:
        verbose: When true, enable DEBUG; otherwise use INFO.

    Returns:
        ``None``. The message format includes severity and message only.
    """
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format="%(levelname)s %(message)s")


def event(name: str, **fields: object) -> None:
    """Emit one ingestion event at INFO with a structured field mapping."""
    LOGGER.info("%s %s", name, fields)


def failure_event(**fields: object) -> None:
    """Emit a processing-failure event at ERROR or WARNING severity.

    Args:
        **fields: Event properties; ``severity == "error"`` selects ERROR,
            all other values select WARNING.

    Returns:
        ``None``; logs under the ``rfp_ingestion`` logger.
    """
    severity = fields.get("severity")
    level = logging.ERROR if severity == "error" else logging.WARNING
    LOGGER.log(level, "processing_failure %s", fields)
