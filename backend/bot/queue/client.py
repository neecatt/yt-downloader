"""Application-facing queue client."""

from __future__ import annotations

import os
from typing import Any


def queue_is_configured() -> bool:
    enabled = os.getenv("TRANSCRIPTION_QUEUE_ENABLED", "true").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        return False
    try:
        from .config import configured
    except ImportError:
        return False
    return configured()


def enqueue_transcription(job_id: str) -> Any:
    """Send only the opaque database ID to Celery; media stays out of Redis."""
    if not queue_is_configured():
        raise RuntimeError("The transcription queue is not configured")
    from ..workers.transcription import process_transcription
    return process_transcription.delay(job_id)
