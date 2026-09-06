"""User-facing status text for durable transcription jobs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..i18n import tr


def retry_status_text(job: dict[str, Any], delay_seconds: int) -> str:
    language = job["language"]
    values = {"attempt": max(1, int(job.get("attempts") or 1))}
    if delay_seconds < 60:
        return tr(language, "transcription_retrying_soon", **values)
    return tr(
        language,
        "transcription_retrying",
        retry_minutes=max(1, (delay_seconds + 59) // 60),
        **values,
    )


def active_job_status_text(job: dict[str, Any], *, now: datetime | None = None) -> str | None:
    """Return a processing/retry message, or None for normal queue position text."""
    language = job["language"]
    if job["status"] == "processing":
        key = "summarization_processing" if job.get("job_type") == "summary" else "transcription_processing"
        return tr(language, key)
    next_attempt_at = job.get("next_attempt_at")
    if not next_attempt_at:
        return None
    remaining = max(0, int((next_attempt_at - (now or datetime.now(timezone.utc))).total_seconds()))
    return retry_status_text(job, remaining) if remaining else None
