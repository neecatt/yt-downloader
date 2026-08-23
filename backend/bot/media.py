from __future__ import annotations

import re
from typing import Any


def format_duration(seconds: int | float | None) -> str:
    if not seconds:
        return "unknown"
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


def safe_filename(title: str, extension: str) -> str:
    cleaned = re.sub(r"[^\w\-. ]+", "", title, flags=re.UNICODE).strip(" .") or "download"
    return f"{cleaned[:80]}.{extension}"


def progress_text(progress: dict[str, Any], fmt: str) -> str:
    status = progress.get("status")
    if status == "finished":
        return "🧩 Download complete. Merging/converting…"
    if status == "started":
        return "🧩 Preparing media…"
    if status == "processing":
        return "🧩 Processing media…"
    if status != "downloading":
        return f"⬇️ Downloading {fmt}…"
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
    return f"⬇️ Downloading {fmt}\n{details}"


def display_error(exc: Exception) -> str:
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
        return "This is an image or carousel post. This bot only downloads videos and audio. Please send an individual video link."
    if "private" in text or "login" in text or "cannot parse data" in text or "requires authentication" in text:
        return "This media is private or requires login. The bot can only access publicly available posts and accounts."
    if "age" in text and "restrict" in text:
        return "This video is age-restricted and cannot be downloaded here."
    if "not available in your country" in text or "geo-restricted" in text or "geo restriction" in text:
        return "This video is unavailable in the downloader's region."
    if "sign in to confirm" in text or "not a bot" in text or "captcha" in text or "javascript" in text or "po token" in text:
        return "YouTube requires an access check. Configure a JavaScript runtime, cookies, or a PO token, then try again."
    if "video unavailable" in text or "content isn't available" in text or "content is unavailable" in text:
        return "YouTube reports that this video is unavailable or no longer public."
    if "403" in text or "forbidden" in text:
        return "The source rejected this server's request. Try configuring cookies or a proxy."
    if "format" in text:
        return "That quality is not available for this video. Try another quality."
    if "size limit" in text or "too large" in text:
        return "The file is too large. Please choose a lower quality or MP3."
    if "timeout" in text or "network" in text or "connection" in text:
        return "The source timed out. Please try again in a moment."
    return "I couldn't download that video. Please check the link and try again."
