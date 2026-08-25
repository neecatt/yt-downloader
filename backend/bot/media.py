from __future__ import annotations

import re
from typing import Any

try:
    from .i18n import tr
except ImportError:
    from bot.i18n import tr


def format_duration(seconds: int | float | None) -> str:
    if not seconds:
        return "unknown"
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


def safe_filename(title: str, extension: str) -> str:
    cleaned = re.sub(r"[^\w\-. ]+", "", title, flags=re.UNICODE).strip(" .") or "download"
    return f"{cleaned[:80]}.{extension}"


def progress_text(progress: dict[str, Any], fmt: str, language: str = "en") -> str:
    status = progress.get("status")
    if status == "finished":
        return tr(language, "progress_finished")
    if status == "started":
        return tr(language, "progress_started")
    if status == "processing":
        return tr(language, "progress_processing")
    if status != "downloading":
        return tr(language, "progress_downloading", fmt=fmt)
    downloaded = progress.get("downloaded_bytes") or 0
    total = progress.get("total_bytes") or progress.get("total_bytes_estimate")
    speed = progress.get("speed")
    eta = progress.get("eta")
    if total:
        percent = max(0.0, min(100.0, downloaded * 100 / total))
        filled = int(percent // 10)
        details = f"{percent:5.1f}%  {'█' * filled}{'░' * (10 - filled)}"
    else:
        details = f"{downloaded / 1024 / 1024:.1f} MB"
    if speed:
        details += f"  {speed / 1024 / 1024:.1f} MB/s"
    if eta is not None:
        details += f"  ETA {int(eta) // 60}:{int(eta) % 60:02d}"
    return f"{tr(language, 'progress_downloading', fmt=fmt)}\n{details}"


def display_error(exc: Exception, language: str = "en") -> str:
    text = str(exc).lower()
    if (
        "image post" in text
        or "photo post" in text
        or "carousel" in text
        or "multiple media" in text
        or "playlist" in text
        or "image-only" in text
        or "image only" in text
    ):
        return tr(language, "video_only")
    if "private" in text or "login" in text or "cannot parse data" in text or "requires authentication" in text:
        return tr(language, "private_error")
    if "age" in text and "restrict" in text:
        return tr(language, "age_error")
    if "not available in your country" in text or "geo-restricted" in text or "geo restriction" in text:
        return tr(language, "geo_error")
    if "sign in to confirm" in text or "not a bot" in text or "captcha" in text or "javascript" in text or "po token" in text:
        return tr(language, "access_error")
    if "video unavailable" in text or "content isn't available" in text or "content is unavailable" in text:
        return tr(language, "unavailable_error")
    if "403" in text or "forbidden" in text:
        return tr(language, "forbidden_error")
    if "format" in text:
        return tr(language, "format_error")
    if "size limit" in text or "too large" in text:
        return tr(language, "size_error")
    if "timeout" in text or "network" in text or "connection" in text:
        return tr(language, "network_error")
    return tr(language, "generic_error")
