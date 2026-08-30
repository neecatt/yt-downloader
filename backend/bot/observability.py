"""Application logging and lightweight timing helpers."""

from __future__ import annotations

import logging
import os
import sys
import time
from typing import Any


def configure_logging() -> None:
    """Configure immediate, structured terminal logs for local and Railway runs."""
    raw_level = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, raw_level, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
        stream=sys.stdout,
        force=True,
    )
    # httpx logs complete request URLs at INFO, which can expose Telegram bot
    # tokens and signed storage URLs. Application events remain at LOG_LEVEL,
    # but transport request logging is intentionally limited to warnings.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def log_timing(logger: logging.Logger, event: str, started: float, **fields: Any) -> None:
    """Emit one consistent timing event using a monotonic duration."""
    values = " ".join(f"{key}={value}" for key, value in fields.items() if value is not None)
    suffix = f" {values}" if values else ""
    logger.info("event=%s duration_seconds=%.2f%s", event, time.perf_counter() - started, suffix)
