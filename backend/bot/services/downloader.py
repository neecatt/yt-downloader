"""yt-dlp download and format-selection service."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import yt_dlp

from ..observability import log_timing
from ..platforms.routing import is_image_or_carousel_info
from ..platforms.security import safe_log_error, safe_log_url, validate_remote_url

LOG = logging.getLogger("downloader_bot.downloader")
ProgressCallback = Callable[[dict[str, Any]], None]
# TikTok's "audio" format is the reused sound rather than the video's soundtrack,
# and its H.265 variants can be silent. Its muxed H.264 formats carry real audio.
AUDIO_FORMAT_SELECTOR = "ba[format_id!=audio]/b[vcodec^=h264]/b[vcodec^=avc]/b/ba"
_NO_AUDIO_STREAM_MARKER = "unable to obtain file audio codec"
NO_AUDIO_ERROR = "This media has no audio track"


@dataclass(frozen=True, slots=True)
class DownloaderConfig:
    max_bytes: int
    fragment_workers: int
    http_chunk_size_mb: int
    cookies_file: str | None
    proxy: str | None
    js_runtime: str | None
    player_client: str | None
    po_token: str | None
    po_provider_url: str | None


def base_options(config: DownloaderConfig, tmpdir: str, progress_callback: ProgressCallback | None = None) -> dict[str, Any]:
    options: dict[str, Any] = {
        "noplaylist": True, "quiet": True, "no_warnings": True, "noprogress": True,
        "retries": 3, "fragment_retries": 3, "file_access_retries": 3,
        "concurrent_fragment_downloads": config.fragment_workers,
        "socket_timeout": 30, "http_timeout": 30, "continuedl": True,
        "overwrites": False, "restrictfilenames": True,
        "paths": {"home": tmpdir}, "outtmpl": {"default": "%(id)s.%(ext)s"},
        "merge_output_format": "mp4", "max_filesize": config.max_bytes,
    }
    if config.cookies_file:
        options["cookiefile"] = config.cookies_file
    if config.proxy:
        options["proxy"] = config.proxy
    if config.js_runtime:
        options["js_runtimes"] = {config.js_runtime: {}}
    extractor_args: dict[str, dict[str, list[str]]] = {}
    youtube_args: dict[str, list[str]] = {}
    if config.po_provider_url:
        player_client = config.player_client
        if not player_client or player_client == "tv_embedded":
            player_client = "mweb"
        youtube_args["player_client"] = [player_client]
        extractor_args["youtubepot-bgutilhttp"] = {"base_url": [config.po_provider_url]}
    elif config.player_client:
        youtube_args["player_client"] = [config.player_client]
    if config.po_token:
        youtube_args["po_token"] = [config.po_token]
    if youtube_args:
        options["extractor_args"] = {"youtube": youtube_args, **extractor_args}
    if progress_callback:
        options["progress_hooks"] = [progress_callback]
        options["postprocessor_hooks"] = [progress_callback]
    return options


def format_options(config: DownloaderConfig, tmpdir: str, fmt: str, progress_callback: ProgressCallback | None = None) -> dict[str, Any]:
    options = base_options(config, tmpdir, progress_callback)
    if fmt.startswith("mp3"):
        bitrate = fmt.split("_", 1)[1] if "_" in fmt else "192"
        if bitrate not in {"128", "192", "320"}:
            raise ValueError("Unsupported MP3 bitrate")
        options.update({"format": AUDIO_FORMAT_SELECTOR, "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": bitrate}]})
        return options
    height = {"360p": 360, "480p": 480, "720p": 720, "1080p": 1080, "2k": 1440}.get(fmt)
    if fmt == "best":
        options["format"] = "bv*+ba/b"
    elif height:
        options["format"] = f"b[height<={height}][ext=mp4]/b[height<={height}]/bv*[height<={height}]+ba/b[height<={height}]/b"
    else:
        raise ValueError("Unsupported format")
    return options


def analyze(config: DownloaderConfig, url: str, tmpdir: str) -> dict[str, Any]:
    started = time.perf_counter()
    validate_remote_url(url)
    options = base_options(config, tmpdir)
    options.update({"quiet": True, "no_warnings": True, "noplaylist": True, "extract_flat": True})
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info:
        raise ValueError("That link did not resolve to a single video")
    if info.get("_type") == "playlist":
        raise ValueError("This is a carousel or multiple-media post")
    if is_image_or_carousel_info(info):
        raise ValueError("This is an image post")
    log_timing(LOG, "analysis_finished", started, source=safe_log_url(url))
    return info


def _discard_audioless_files(url: str, tmpdir: str) -> None:
    # With overwrites disabled, a retry would otherwise reuse the same bad file.
    for path in Path(tmpdir).rglob("*"):
        if path.is_file():
            LOG.warning("event=download_no_audio_stream source=%s extension=%s size_bytes=%s", safe_log_url(url), path.suffix.lstrip("."), path.stat().st_size)
            path.unlink(missing_ok=True)


def download(config: DownloaderConfig, url: str, fmt: str, tmpdir: str, progress_callback: ProgressCallback | None = None) -> tuple[dict[str, Any], Path, str]:
    started = time.perf_counter()
    validate_remote_url(url)
    LOG.info("event=download_started source=%s format=%s", safe_log_url(url), fmt)
    options = format_options(config, tmpdir, fmt, progress_callback)
    for attempt in range(2):
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=True)
            files = [p for p in Path(tmpdir).rglob("*") if p.is_file() and not p.name.endswith((".part", ".ytdl"))]
            if not files:
                raise FileNotFoundError("yt-dlp did not produce a file")
            filename = max(files, key=lambda path: path.stat().st_size)
            if filename.stat().st_size > config.max_bytes:
                raise ValueError("The downloaded file exceeds the configured size limit")
            extension = "mp3" if fmt.startswith("mp3") else filename.suffix.lstrip(".").lower() or "mp4"
            log_timing(LOG, "download_finished", started, source=safe_log_url(url), format=fmt, size_bytes=filename.stat().st_size)
            return info, filename, extension
        except Exception as exc:
            LOG.warning("event=download_attempt_failed attempt=%s format=%s error=%s", attempt + 1, fmt, safe_log_error(exc))
            no_audio = _NO_AUDIO_STREAM_MARKER in str(exc)
            if no_audio:
                _discard_audioless_files(url, tmpdir)
            if attempt == 1:
                if no_audio:
                    raise ValueError(NO_AUDIO_ERROR) from exc
                raise
            if "403" in str(exc):
                options["http_chunk_size"] = config.http_chunk_size_mb * 1024 * 1024
                options["continuedl"] = False
                options["overwrites"] = True
                for partial in Path(tmpdir).rglob("*"):
                    if partial.is_file() and partial.name.endswith((".part", ".ytdl")):
                        partial.unlink(missing_ok=True)
            time.sleep(2)
    raise RuntimeError("download failed")
