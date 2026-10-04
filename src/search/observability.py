"""Emit structured search events through the package logger."""

from __future__ import annotations

import logging

LOGGER = logging.getLogger("rfp_search")


def event(name: str, **fields: object) -> None:
    """Log one named event with its associated structured fields.

    Args:
        name: Event name written as the first log message value.
        **fields: Event properties logged as a mapping.

    Returns:
        ``None``. Emits an INFO record on the ``rfp_search`` logger.
    """
    LOGGER.info("%s %s", name, fields)
