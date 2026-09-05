"""Pure retry policy shared by workers and regression tests."""

from __future__ import annotations


_PERMANENT_MARKERS = (
    "private",
    "not found",
    "video is unavailable",
    "this video is unavailable",
    "unavailable in the downloader's region",
    "age-restricted",
    "age restricted",
    "unsupported",
    "invalid url",
    "invalid video url",
    "larger than the transcription limit",
)


def retryable(error: Exception) -> bool:
    """Keep infrastructure/model failures durable; fail clear input errors."""
    text = str(error).lower()
    return not any(marker in text for marker in _PERMANENT_MARKERS)


def retry_delay_seconds(retry_number: int) -> int:
    """Short exponential delay before Celery's bounded retry attempts."""
    return min(300, 2 ** max(0, retry_number) * 10)
