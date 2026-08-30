"""Modal-backed speech-to-text integration.

Railway downloads the source audio using the bot's existing yt-dlp setup,
uploads it temporarily to private R2, and sends only that signed URL to Modal.
The bot container does not need a GPU or a local model cache.
"""

from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import urlparse


DEFAULT_APP_NAME = "yt-downloader-transcriber"
DEFAULT_FUNCTION_NAME = "transcribe"
MAX_TRANSCRIPT_CHARS = 2_000_000
TRANSCRIPTION_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be",
    "tiktok.com", "www.tiktok.com", "vm.tiktok.com", "vt.tiktok.com",
    "instagram.com", "www.instagram.com", "facebook.com", "www.facebook.com",
    "m.facebook.com", "web.facebook.com", "fb.watch",
    "x.com", "www.x.com", "twitter.com", "mobile.twitter.com",
    "linkedin.com", "www.linkedin.com", "lnkd.in",
}


def _truthy(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def transcription_is_configured() -> bool:
    """Return whether the Railway side can authenticate to Modal."""
    return (
        _truthy(os.getenv("TRANSCRIPTION_ENABLED"), default=True)
        and bool(os.getenv("MODAL_TOKEN_ID", "").strip())
        and bool(os.getenv("MODAL_TOKEN_SECRET", "").strip())
        and bool(os.getenv("MODAL_APP_NAME", DEFAULT_APP_NAME).strip())
        and bool(os.getenv("MODAL_FUNCTION_NAME", DEFAULT_FUNCTION_NAME).strip())
    )


def validate_transcription_url(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not parsed.netloc or host not in TRANSCRIPTION_HOSTS:
        raise ValueError("Only supported public HTTPS video links can be transcribed")
    if parsed.username or parsed.password:
        raise ValueError("Authenticated source links are not supported")
    return url


def _function_handle() -> Any:
    import modal

    return modal.Function.from_name(
        os.getenv("MODAL_APP_NAME", DEFAULT_APP_NAME).strip(),
        os.getenv("MODAL_FUNCTION_NAME", DEFAULT_FUNCTION_NAME).strip(),
    )


def transcribe_audio_url_sync(audio_url: str, title: str = "Transcript", duration: float | None = None) -> dict[str, Any]:
    """Send a temporary private R2 audio URL to Modal for inference."""
    parsed = urlparse(audio_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("The temporary transcription URL is invalid")
    if not transcription_is_configured():
        raise RuntimeError("Transcription is not configured")
    result = _function_handle().remote(audio_url, title[:300], "r2", duration)
    if not isinstance(result, dict):
        raise RuntimeError("The transcription service returned an invalid response")
    text = str(result.get("text") or "").strip()
    if not text:
        raise RuntimeError("No speech was detected in this media")
    if len(text) > MAX_TRANSCRIPT_CHARS:
        raise RuntimeError("The transcript is too large to send")
    return {
        "title": str(result.get("title") or "Transcript")[:300],
        "language": str(result.get("language") or "unknown")[:32],
        "duration": result.get("duration"),
        "text": text,
        "segments": result.get("segments") or [],
    }


def transcribe_url_sync(url: str) -> dict[str, Any]:
    """Backward-compatible direct invocation for callers outside the bot."""
    validate_transcription_url(url)
    if not transcription_is_configured():
        raise RuntimeError("Transcription is not configured")
    result = _function_handle().remote(url, "Transcript", "source")
    if not isinstance(result, dict):
        raise RuntimeError("The transcription service returned an invalid response")
    return result


def _timestamp(seconds: Any) -> str:
    try:
        total = max(0, int(float(seconds)))
    except (TypeError, ValueError):
        return "00:00"
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"


def format_transcript(result: dict[str, Any]) -> str:
    """Create a useful plain-text artifact without trusting source markup."""
    title = re.sub(r"\s+", " ", str(result.get("title") or "Transcript")).strip()
    language = re.sub(r"\s+", " ", str(result.get("language") or "unknown")).strip()
    lines = [f"{title}", f"Detected language: {language}", "", "Transcript", ""]
    segments = result.get("segments") or []
    if isinstance(segments, list) and segments:
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            text = re.sub(r"\s+", " ", str(segment.get("text") or "")).strip()
            if text:
                lines.append(f"[{_timestamp(segment.get('start'))}] {text}")
    if len(lines) == 5:
        lines.append(str(result.get("text") or "").strip())
    return "\n".join(lines).strip() + "\n"


def transcript_filename(title: str) -> str:
    clean = re.sub(r"[^\w\-. ]+", "", title, flags=re.UNICODE).strip() or "transcript"
    return f"{clean[:120]}.txt"
