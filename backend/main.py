"""Telegram video downloader bot.

The bot keeps only short-lived callback state in memory. Downloads run in a
thread pool because yt-dlp and ffmpeg are blocking processes; Telegram API
calls remain asynchronous.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os
import re
import secrets
import tempfile
import time
import threading
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse, urlsplit, urlunsplit

import yt_dlp
try:
    from .bot.cookies import prepare_cookie_file as _prepare_cookie_file
    from .bot.media import display_error, format_duration, progress_text, safe_filename
    from .bot.limits import SlidingWindowLimiter
    from .bot.r2_cleanup import cleanup_loop, schedule_object_delete
    from .bot.security import (
        extract_url as _extract_url,
        safe_log_error,
        safe_log_url,
        validate_donation_url,
        validate_remote_url,
    )
except ImportError:  # Supports running `python main.py` in backend.
    from bot.cookies import prepare_cookie_file as _prepare_cookie_file
    from bot.media import display_error, format_duration, progress_text, safe_filename
    from bot.limits import SlidingWindowLimiter
    from bot.r2_cleanup import cleanup_loop, schedule_object_delete
    from bot.security import (
        extract_url as _extract_url,
        safe_log_error,
        safe_log_url,
        validate_donation_url,
        validate_remote_url,
    )
try:
    from dotenv import load_dotenv
except ImportError:  # Keeps the bot usable in the old local virtualenv.
    def load_dotenv() -> None:
        env_file = Path(__file__).with_name(".env")
        if not env_file.is_file():
            return
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.error import BadRequest, TelegramError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

LOG = logging.getLogger("downloader_bot")

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MAX_UPLOAD_BYTES = min(4096, max(1, int(os.getenv("TELEGRAM_MAX_UPLOAD_MB", "49")))) * 1024 * 1024
MAX_DOWNLOAD_BYTES = min(4096, max(1, int(os.getenv("MAX_DOWNLOAD_MB", "2048")))) * 1024 * 1024
MAX_URL_LENGTH = max(256, int(os.getenv("MAX_URL_LENGTH", "4096")))
STATE_TTL_SECONDS = min(86400, max(60, int(os.getenv("CALLBACK_STATE_TTL_SECONDS", "1800"))))
MAX_STATE_ENTRIES = min(100000, max(100, int(os.getenv("MAX_STATE_ENTRIES", "10000"))))
MAX_WORKERS = min(8, max(1, int(os.getenv("DOWNLOAD_WORKERS", "2"))))
FRAGMENT_WORKERS = min(16, max(1, int(os.getenv("FRAGMENT_WORKERS", "4"))))
R2_UPLOAD_CONCURRENCY = min(32, max(1, int(os.getenv("R2_UPLOAD_CONCURRENCY", "8"))))
HTTP_CHUNK_SIZE_MB = max(1, int(os.getenv("HTTP_CHUNK_SIZE_MB", "10")))
YTDLP_COOKIES_FILE = os.getenv("YTDLP_COOKIES_FILE")
YTDLP_COOKIES_B64 = os.getenv("YTDLP_COOKIES_B64")
YTDLP_PROXY = os.getenv("YTDLP_PROXY")
YTDLP_PLAYER_CLIENT = os.getenv("YTDLP_PLAYER_CLIENT")
YTDLP_PO_TOKEN = os.getenv("YTDLP_PO_TOKEN")
YTDLP_POT_PROVIDER_URL = os.getenv("YTDLP_POT_PROVIDER_URL")
YTDLP_JS_RUNTIME = os.getenv("YTDLP_JS_RUNTIME")
TELEGRAM_API_BASE_URL = os.getenv("TELEGRAM_API_BASE_URL")
TELEGRAM_API_FILE_BASE_URL = os.getenv("TELEGRAM_API_FILE_BASE_URL")
DELIVERY_MODE = os.getenv("DELIVERY_MODE", "telegram").lower()
ALLOW_GENERIC_HTTPS = os.getenv("ALLOW_GENERIC_HTTPS", "false").lower() in {"1", "true", "yes"}
DONATION_URL_RAW = os.getenv("DONATION_URL", "").strip()
DONATION_PROMPTS_ENABLED = os.getenv("DONATION_PROMPTS_ENABLED", "true").lower() in {"1", "true", "yes"}
DONATION_PROMPT_COOLDOWN_SECONDS = max(0, int(os.getenv("DONATION_PROMPT_COOLDOWN_HOURS", "24"))) * 3600
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID")
R2_ENDPOINT_URL = os.getenv("R2_ENDPOINT_URL") or (f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com" if R2_ACCOUNT_ID else None)
R2_API_TOKEN = os.getenv("R2_API_TOKEN")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
if R2_API_TOKEN and ":" in R2_API_TOKEN:
    R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY = R2_API_TOKEN.split(":", 1)
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME")
R2_PUBLIC_BASE_URL = os.getenv("R2_PUBLIC_BASE_URL")
R2_PRESIGNED_URL_TTL = min(604800, max(60, int(os.getenv("R2_PRESIGNED_URL_TTL_SECONDS", "86400"))))
R2_CLEANUP_INTERVAL_SECONDS = max(30, int(os.getenv("R2_CLEANUP_INTERVAL_SECONDS", "60")))
# Keep object retention tied to the URL lifetime so cleanup cannot leave
# expired downloads stored longer than necessary or delete them prematurely.
R2_OBJECT_RETENTION_SECONDS = R2_PRESIGNED_URL_TTL
ADMIN_API_TOKEN = os.getenv("ADMIN_API_TOKEN", "")
ADMIN_API_ENABLED = os.getenv("ADMIN_API_ENABLED", "true").lower() in {"1", "true", "yes"}
ADMIN_API_HOST = os.getenv("ADMIN_API_HOST", "0.0.0.0")
ADMIN_API_PORT = int(os.getenv("ADMIN_API_PORT", os.getenv("PORT", "8080")))
DOWNLOADS_PER_USER_PER_HOUR = min(100, max(1, int(os.getenv("DOWNLOADS_PER_USER_PER_HOUR", "10"))))
DOWNLOADS_PER_USER_PER_DAY = min(500, max(DOWNLOADS_PER_USER_PER_HOUR, int(os.getenv("DOWNLOADS_PER_USER_PER_DAY", "20"))))
ANALYSES_PER_USER_PER_HOUR = min(100, max(1, int(os.getenv("ANALYSES_PER_USER_PER_HOUR", "20"))))
DOWNLOADS_GLOBAL_PER_HOUR = min(1000, max(1, int(os.getenv("DOWNLOADS_GLOBAL_PER_HOUR", "100"))))
ANALYSES_GLOBAL_PER_HOUR = min(2000, max(1, int(os.getenv("ANALYSES_GLOBAL_PER_HOUR", "300"))))

# Telegram callback data is limited to 64 bytes. A random opaque key keeps
# URLs and user input out of callback data and prevents cross-chat reuse.
SUPPORTED_CHAT_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be",
    "tiktok.com", "www.tiktok.com", "vm.tiktok.com", "vt.tiktok.com",
    "instagram.com", "www.instagram.com", "facebook.com", "www.facebook.com",
    "m.facebook.com", "web.facebook.com", "fb.watch",
}


DONATION_URL = validate_donation_url(DONATION_URL_RAW)


@dataclass(slots=True)
class LinkState:
    url: str
    chat_id: int
    user_id: int
    created_at: float
    title: str = "Video"
    duration: int | None = None
    activity_id: str | None = None


STATES: dict[str, LinkState] = {}
DOWNLOAD_LOCKS: dict[int, asyncio.Lock] = {}
SUPPORT_PROMPT_LAST_SHOWN: dict[tuple[int, int], float] = {}
EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="download")
DOWNLOAD_LIMITER = SlidingWindowLimiter()
ANALYSIS_LIMITER = SlidingWindowLimiter()
ProgressCallback = Callable[[dict[str, Any]], None]


def prepare_cookie_file() -> str | None:
    return _prepare_cookie_file(YTDLP_COOKIES_B64, YTDLP_COOKIES_FILE)


YTDLP_EFFECTIVE_COOKIES_FILE = prepare_cookie_file()


def extract_url(text: str, *, any_https: bool = False) -> str | None:
    return _extract_url(text, any_https=any_https, max_length=MAX_URL_LENGTH)


def allow_analysis(user_id: int) -> bool:
    return ANALYSIS_LIMITER.allow(
        user_id,
        limit=ANALYSES_PER_USER_PER_HOUR,
        window_seconds=3600,
    ) and ANALYSIS_LIMITER.allow(
        "global",
        limit=ANALYSES_GLOBAL_PER_HOUR,
        window_seconds=3600,
    )


def allow_download(user_id: int) -> bool:
    return DOWNLOAD_LIMITER.allow(
        (user_id, "hour"),
        limit=DOWNLOADS_PER_USER_PER_HOUR,
        window_seconds=3600,
    ) and DOWNLOAD_LIMITER.allow(
        (user_id, "day"),
        limit=DOWNLOADS_PER_USER_PER_DAY,
        window_seconds=86400,
    ) and DOWNLOAD_LIMITER.allow(
        "global",
        limit=DOWNLOADS_GLOBAL_PER_HOUR,
        window_seconds=3600,
    )


def prune_states() -> None:
    cutoff = time.monotonic() - STATE_TTL_SECONDS
    for key, state in list(STATES.items()):
        if state.created_at < cutoff:
            STATES.pop(key, None)
    if len(STATES) > MAX_STATE_ENTRIES:
        excess = len(STATES) - MAX_STATE_ENTRIES
        for key, _ in sorted(STATES.items(), key=lambda item: item[1].created_at)[:excess]:
            STATES.pop(key, None)


def save_state(update: Update, url: str, info: dict[str, Any] | None = None) -> str:
    prune_states()
    message = update.effective_message
    user = update.effective_user
    key = secrets.token_urlsafe(9)
    activity_id = _create_activity_event(update, url, info)
    STATES[key] = LinkState(
        url=url,
        chat_id=update.effective_chat.id,
        user_id=user.id if user else 0,
        created_at=time.monotonic(),
        title=(info or {}).get("title", "Video"),
        duration=(info or {}).get("duration"),
        activity_id=activity_id,
    )
    prune_states()
    return key


def _activity_platform(url: str) -> str:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if "youtube" in host or host == "youtu.be": return "youtube"
    if "instagram" in host: return "instagram"
    if "facebook" in host or host == "fb.watch": return "facebook"
    if "tiktok" in host: return "tiktok"
    return "other"


def _create_activity_event(update: Update, url: str, info: dict[str, Any] | None) -> str | None:
    try:
        try:
            from .bot import activity_store
        except ImportError:
            from bot import activity_store
        if not activity_store.enabled():
            return None
        user = update.effective_user
        chat = update.effective_chat
        return activity_store.create_event(
            username=f"@{getattr(user, 'username', '')}" if getattr(user, "username", None) else None,
            display_name=getattr(user, "full_name", None) if user else None,
            chat_type=getattr(chat, "type", None) if chat else None,
            source_url=url,
            title=(info or {}).get("title"),
            platform=_activity_platform(url),
            action="download",
        )
    except Exception:
        LOG.warning("Could not initialize activity event", exc_info=True)
        return None


def _update_activity(event_id: str | None, **kwargs: Any) -> None:
    try:
        from .bot import activity_store
    except ImportError:
        from bot import activity_store
    activity_store.update_event(event_id, **kwargs)


def get_state(key: str, update: Update) -> LinkState | None:
    state = STATES.get(key)
    if not state or state.chat_id != update.effective_chat.id:
        return None
    user = update.effective_user
    if state.user_id and user and state.user_id != user.id:
        return None
    if time.monotonic() - state.created_at > STATE_TTL_SECONDS:
        STATES.pop(key, None)
        return None
    return state


def support_is_configured() -> bool:
    return DONATION_PROMPTS_ENABLED and bool(DONATION_URL)


def support_prompt_allowed(chat_id: int, user_id: int, now: float | None = None) -> bool:
    if not support_is_configured():
        return False
    current = time.monotonic() if now is None else now
    last_shown = SUPPORT_PROMPT_LAST_SHOWN.get((chat_id, user_id))
    return last_shown is None or current - last_shown >= DONATION_PROMPT_COOLDOWN_SECONDS


def mark_support_prompt_shown(chat_id: int, user_id: int, now: float | None = None) -> None:
    SUPPORT_PROMPT_LAST_SHOWN[(chat_id, user_id)] = time.monotonic() if now is None else now


def support_keyboard() -> InlineKeyboardMarkup | None:
    if not support_is_configured():
        return None
    buttons = [InlineKeyboardButton("☕ Support this bot", url=DONATION_URL)]
    return InlineKeyboardMarkup([buttons])


async def send_support_prompt(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int, *, force: bool = False) -> bool:
    if not force and not support_prompt_allowed(chat_id, user_id):
        return False
    markup = support_keyboard()
    if not markup:
        return False
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "If this bot saved you time, you can support its hosting costs. "
            "Donations are optional and the bot remains free."
        ),
        reply_markup=markup,
    )
    if not force:
        mark_support_prompt_shown(chat_id, user_id)
    return True


def r2_is_configured() -> bool:
    values = (R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME)
    return all(value and not value.startswith("your-") for value in values) and urlsplit(R2_ENDPOINT_URL).scheme == "https"


def r2_client():
    """Create an R2 S3 client, accepting either account or bucket endpoint URLs."""
    if not r2_is_configured():
        raise RuntimeError("R2 storage is not configured")
    import boto3

    parsed = urlsplit(R2_ENDPOINT_URL)
    path_parts = [part for part in parsed.path.split("/") if part]
    if path_parts and path_parts[-1] == R2_BUCKET_NAME:
        endpoint_url = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
    else:
        endpoint_url = R2_ENDPOINT_URL
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )


def upload_to_r2(filename: Path, info: dict[str, Any], extension: str) -> str:
    """Upload a completed file and return a temporary browser download URL."""
    from boto3.s3.transfer import TransferConfig

    title = info.get("title", "download")
    download_name = safe_filename(title, extension)
    object_key = f"downloads/{datetime.now(timezone.utc):%Y/%m/%d}/{secrets.token_urlsafe(12)}-{download_name}"
    client = r2_client()
    transfer_config = TransferConfig(
        multipart_threshold=32 * 1024 * 1024,
        multipart_chunksize=16 * 1024 * 1024,
        max_concurrency=R2_UPLOAD_CONCURRENCY,
        use_threads=True,
    )
    client.upload_file(
        str(filename),
        R2_BUCKET_NAME,
        object_key,
        ExtraArgs={"ContentType": "audio/mpeg" if extension == "mp3" else "video/mp4" if extension == "mp4" else "application/octet-stream"},
        Config=transfer_config,
    )
    schedule_object_delete(
        r2_client,
        R2_BUCKET_NAME,
        object_key,
        delay_seconds=R2_OBJECT_RETENTION_SECONDS,
    )
    if R2_PUBLIC_BASE_URL:
        LOG.warning("R2_PUBLIC_BASE_URL is ignored; temporary downloads require private presigned URLs")
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": R2_BUCKET_NAME, "Key": object_key, "ResponseContentDisposition": f'attachment; filename="{download_name}"'},
        ExpiresIn=R2_PRESIGNED_URL_TTL,
    )


def ydl_base_options(tmpdir: str, progress_callback: ProgressCallback | None = None) -> dict[str, Any]:
    options: dict[str, Any] = {
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "retries": 3,
        "fragment_retries": 3,
        "file_access_retries": 3,
        "concurrent_fragment_downloads": FRAGMENT_WORKERS,
        "socket_timeout": 30,
        "http_timeout": 30,
        "continuedl": True,
        "overwrites": False,
        "restrictfilenames": True,
        "paths": {"home": tmpdir},
        "outtmpl": {"default": "%(id)s.%(ext)s"},
        "merge_output_format": "mp4",
        "max_filesize": MAX_DOWNLOAD_BYTES,
    }
    if YTDLP_EFFECTIVE_COOKIES_FILE:
        options["cookiefile"] = YTDLP_EFFECTIVE_COOKIES_FILE
    if YTDLP_PROXY:
        options["proxy"] = YTDLP_PROXY
    if YTDLP_JS_RUNTIME:
        options["js_runtimes"] = {YTDLP_JS_RUNTIME: {}}
    extractor_args: dict[str, dict[str, list[str]]] = {}
    youtube_args: dict[str, list[str]] = {}
    if YTDLP_POT_PROVIDER_URL:
        # The current yt-dlp guidance recommends mweb with a PO-token
        # provider. The old tv_embedded client is no longer a safe default.
        provider_client = YTDLP_PLAYER_CLIENT or "mweb"
        if provider_client == "tv_embedded":
            provider_client = "mweb"
        youtube_args["player_client"] = [provider_client]
        extractor_args["youtubepot-bgutilhttp"] = {"base_url": [YTDLP_POT_PROVIDER_URL]}
    elif YTDLP_PLAYER_CLIENT:
        youtube_args["player_client"] = [YTDLP_PLAYER_CLIENT]
    if YTDLP_PO_TOKEN:
        youtube_args["po_token"] = [YTDLP_PO_TOKEN]
    if youtube_args:
        extractor_args["youtube"] = youtube_args
        options["extractor_args"] = extractor_args
    if progress_callback:
        options["progress_hooks"] = [progress_callback]
        options["postprocessor_hooks"] = [progress_callback]
    return options


def ydl_options(tmpdir: str, fmt: str, progress_callback: ProgressCallback | None = None) -> dict[str, Any]:
    options = ydl_base_options(tmpdir, progress_callback)
    if fmt.startswith("mp3"):
        bitrate = fmt.split("_", 1)[1] if "_" in fmt else "192"
        if bitrate not in {"128", "192", "320"}:
            raise ValueError("Unsupported MP3 bitrate")
        options.update({
            "format": "bestaudio/best",
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": bitrate}],
        })
    else:
        height = {"360p": 360, "480p": 480, "720p": 720, "1080p": 1080, "2k": 1440}.get(fmt)
        if fmt == "best":
            options["format"] = "bv*+ba/b"
        elif height:
            # Prefer progressive MP4. Some YouTube DASH media URLs currently
            # return 403 without a PO token, while progressive MP4 works for
            # many public videos.
            options["format"] = f"b[height<={height}][ext=mp4]/b[height<={height}]/bv*[height<={height}]+ba/b[height<={height}]/b"
        else:
            raise ValueError("Unsupported format")
    return options


def analyze_url(url: str) -> dict[str, Any]:
    validate_remote_url(url)
    options = ydl_base_options(tempfile.gettempdir())
    options.update({"quiet": True, "no_warnings": True, "noplaylist": True, "extract_flat": True})
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info or info.get("_type") == "playlist":
        raise ValueError("That link did not resolve to a single video")
    return info


def download_sync(url: str, fmt: str, tmpdir: str, progress_callback: ProgressCallback | None = None) -> tuple[dict[str, Any], Path, str]:
    validate_remote_url(url)
    options = ydl_options(tmpdir, fmt, progress_callback)
    for attempt in range(2):
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=True)
            files = [p for p in Path(tmpdir).rglob("*") if p.is_file() and not p.name.endswith((".part", ".ytdl"))]
            if not files:
                raise FileNotFoundError("yt-dlp did not produce a file")
            filename = max(files, key=lambda path: path.stat().st_size)
            if filename.stat().st_size > MAX_DOWNLOAD_BYTES:
                raise ValueError("The downloaded file exceeds the configured size limit")
            extension = "mp3" if fmt.startswith("mp3") else filename.suffix.lstrip(".") or "mp4"
            return info, filename, extension
        except Exception as exc:
            if attempt == 1:
                raise
            if "403" in str(exc):
                # Some YouTube media URLs reject a full request but allow
                # byte-range requests. Retry those URLs in bounded chunks.
                options["http_chunk_size"] = HTTP_CHUNK_SIZE_MB * 1024 * 1024
                options["continuedl"] = False
                options["overwrites"] = True
                for partial in Path(tmpdir).rglob("*"):
                    if partial.is_file() and partial.name.endswith((".part", ".ytdl")):
                        partial.unlink(missing_ok=True)
            time.sleep(2)
    raise RuntimeError("download failed")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "Send a YouTube, TikTok, Instagram, or Facebook link, or use /download <https-url>.\n\n"
        "Choose a quality, then I’ll download it and send it back.\n"
        "Use /support if you would like to help keep the bot running.",
        reply_markup=support_keyboard(),
    )


async def support_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not support_is_configured():
        await update.effective_message.reply_text(
            "Support is not configured yet, but the bot remains free to use."
        )
        return
    await send_support_prompt(context, update.effective_chat.id, update.effective_user.id, force=True)


async def make_choice(update: Update, url: str, info: dict[str, Any] | None = None) -> None:
    key = save_state(update, url, info)
    title = (info or {}).get("title", "Video")
    duration = (info or {}).get("duration")
    duration_line = f"\n⏱ Duration: {format_duration(duration)}" if duration else ""
    keyboard = [
        [InlineKeyboardButton("360p · fast", callback_data=f"d|360p|{key}"), InlineKeyboardButton("480p", callback_data=f"d|480p|{key}")],
        [InlineKeyboardButton("720p", callback_data=f"d|720p|{key}"), InlineKeyboardButton("1080p", callback_data=f"d|1080p|{key}")],
        [InlineKeyboardButton("Best quality", callback_data=f"d|best|{key}")],
        [InlineKeyboardButton("MP3 · 128 kbps", callback_data=f"d|mp3_128|{key}"), InlineKeyboardButton("MP3 · 192 kbps", callback_data=f"d|mp3_192|{key}")],
        [InlineKeyboardButton("MP3 · 320 kbps", callback_data=f"d|mp3_320|{key}")],
    ]
    await update.effective_message.reply_text(
        f"🎬 {title}{duration_line}\n\nChoose a format:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def download_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.effective_message.reply_text("Usage: /download <https-url>")
        return
    url = extract_url(context.args[0], any_https=ALLOW_GENERIC_HTTPS)
    if not url:
        await update.effective_message.reply_text("Please provide one valid HTTPS video URL.")
        return
    user_id = update.effective_user.id if update.effective_user else 0
    if not allow_analysis(user_id):
        await update.effective_message.reply_text("You have reached the hourly link-analysis limit. Please try again later.")
        return
    status = await update.effective_message.reply_text("🔎 Analyzing the link…")
    try:
        info = await asyncio.get_running_loop().run_in_executor(EXECUTOR, analyze_url, url)
        await status.delete()
        await make_choice(update, url, info)
    except Exception as exc:
        LOG.info("analysis failed for %s: %s", safe_log_url(url), safe_log_error(exc))
        await status.edit_text(display_error(exc))


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.effective_message.text or ""
    url = extract_url(text)
    if not url:
        await update.effective_message.reply_text("Please send a YouTube, TikTok, Instagram, or Facebook HTTPS link.")
        return
    await make_choice(update, url)


async def send_file(context: ContextTypes.DEFAULT_TYPE, chat_id: int, filename: Path, info: dict[str, Any], extension: str, fmt: str) -> None:
    size = filename.stat().st_size
    if size > MAX_UPLOAD_BYTES:
        raise ValueError("The file is too large for the configured Telegram upload limit")
    title = info.get("title", "Downloaded video")
    name = safe_filename(title, extension)
    caption = f"{title[:900]} · {fmt}"
    with filename.open("rb") as media:
        if extension == "mp3":
            await context.bot.send_audio(chat_id=chat_id, audio=media, filename=name, title=title[:64], caption=caption)
        elif extension == "mp4":
            await context.bot.send_video(chat_id=chat_id, video=media, filename=name, supports_streaming=True, caption=caption, read_timeout=300, write_timeout=300)
        else:
            await context.bot.send_document(chat_id=chat_id, document=media, filename=name, caption=caption, read_timeout=300, write_timeout=300)


async def send_r2_link(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    url: str,
    info: dict[str, Any],
    fmt: str,
    size_bytes: int | None = None,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    title = info.get("title", "Downloaded file")
    size_text = f"{size_bytes / 1024 / 1024:.1f} MB" if size_bytes else "large"
    download_button = [InlineKeyboardButton("⬇️ Download file", url=url)]
    keyboard_rows = [download_button]
    if reply_markup:
        keyboard_rows.extend(reply_markup.inline_keyboard)
    keyboard = InlineKeyboardMarkup(keyboard_rows)
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"✅ Ready: {title[:700]}\nFormat: {fmt}\nSize: {size_text}\n\n"
            "The media exceeds Telegram's upload limit, so I’m giving you a "
            "temporary download link instead."
        ),
        reply_markup=keyboard,
    )


async def run_download_with_progress(
    loop: asyncio.AbstractEventLoop,
    url: str,
    fmt: str,
    tmpdir: str,
    query: Any,
) -> tuple[dict[str, Any], Path, str]:
    """Run yt-dlp and throttle progress edits to Telegram-friendly updates."""
    progress_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    def on_progress(payload: dict[str, Any]) -> None:
        loop.call_soon_threadsafe(progress_queue.put_nowait, payload)

    download_task = loop.run_in_executor(EXECUTOR, download_sync, url, fmt, tmpdir, on_progress)
    last_update = 0.0
    latest: dict[str, Any] | None = None
    while not download_task.done():
        try:
            latest = await asyncio.wait_for(progress_queue.get(), timeout=0.5)
        except asyncio.TimeoutError:
            continue
        now = time.monotonic()
        if now - last_update >= 1.5 or latest.get("status") in {"finished", "started", "processing"}:
            try:
                await query.edit_message_text(progress_text(latest, fmt))
                last_update = now
            except TelegramError:
                LOG.debug("Unable to update download progress", exc_info=True)
    result = await download_task
    while not progress_queue.empty():
        latest = progress_queue.get_nowait()
    if latest and latest.get("status") == "finished":
        try:
            await query.edit_message_text(progress_text(latest, fmt))
        except TelegramError:
            LOG.debug("Unable to update final download progress", exc_info=True)
    return result


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    try:
        _, fmt, key = query.data.split("|", 2)
    except (AttributeError, ValueError):
        await query.edit_message_text("That button is no longer valid. Please send the link again.")
        return
    state = get_state(key, update)
    if not state:
        await query.edit_message_text("That link has expired. Please send it again.")
        return
    lock = DOWNLOAD_LOCKS.setdefault(state.chat_id, asyncio.Lock())
    if lock.locked():
        await query.edit_message_text("A download is already running in this chat. Please wait for it to finish.")
        return
    async with lock:
        if not allow_download(state.user_id):
            await query.edit_message_text("You have reached the download limit. Please try again later.")
            return
        await query.edit_message_text(f"⬇️ Downloading {fmt}…")
        await context.bot.send_chat_action(chat_id=state.chat_id, action=ChatAction.UPLOAD_DOCUMENT)
        try:
            with tempfile.TemporaryDirectory(prefix="ytbot-") as tmpdir:
                loop = asyncio.get_running_loop()
                info, filename, extension = await run_download_with_progress(loop, state.url, fmt, tmpdir, query)
                file_size = filename.stat().st_size
                delivery = None
                if DELIVERY_MODE == "r2":
                    await query.edit_message_text("☁️ Uploading to cloud storage…\nDownload: 100%")
                    download_url = await loop.run_in_executor(EXECUTOR, upload_to_r2, filename, info, extension)
                    offer_support = support_prompt_allowed(state.chat_id, state.user_id)
                    await send_r2_link(
                        context, state.chat_id, download_url, info, fmt, file_size,
                        support_keyboard() if offer_support else None,
                    )
                    if offer_support:
                        mark_support_prompt_shown(state.chat_id, state.user_id)
                    delivery = "r2"
                elif DELIVERY_MODE == "auto" and file_size > MAX_UPLOAD_BYTES and r2_is_configured():
                    await query.edit_message_text("☁️ Uploading to cloud storage…\nDownload: 100%")
                    download_url = await loop.run_in_executor(EXECUTOR, upload_to_r2, filename, info, extension)
                    offer_support = support_prompt_allowed(state.chat_id, state.user_id)
                    await send_r2_link(
                        context, state.chat_id, download_url, info, fmt, file_size,
                        support_keyboard() if offer_support else None,
                    )
                    if offer_support:
                        mark_support_prompt_shown(state.chat_id, state.user_id)
                    delivery = "r2"
                elif file_size <= MAX_UPLOAD_BYTES:
                    await query.edit_message_text("⬆️ Uploading to Telegram…\nDownload: 100%")
                    await send_file(context, state.chat_id, filename, info, extension, fmt)
                    await send_support_prompt(context, state.chat_id, state.user_id)
                    delivery = "telegram"
                else:
                    raise ValueError("The file exceeds Telegram's upload limit and cloud delivery is not configured")
                _update_activity(state.activity_id, status="completed", fmt=fmt, delivery=delivery, size_bytes=file_size, duration_ms=int(info.get("duration", 0) * 1000) if info.get("duration") else None, title=info.get("title"))
                await query.delete_message()
        except (TelegramError, BadRequest):
            LOG.exception("Telegram upload failed for chat %s", state.chat_id)
            _update_activity(state.activity_id, status="failed", error="Telegram could not accept the file")
            await query.edit_message_text("Telegram could not accept the file. Try a lower quality.")
        except Exception as exc:
            LOG.info("download failed for %s: %s", safe_log_url(state.url), safe_log_error(exc))
            _update_activity(state.activity_id, status="failed", error=display_error(exc))
            await query.edit_message_text(f"❌ {display_error(exc)}")
        finally:
            STATES.pop(key, None)


R2_CLEANUP_TASK: asyncio.Task[Any] | None = None


async def post_init(application: Application) -> None:
    global R2_CLEANUP_TASK
    LOG.info("Bot started with %s download worker(s)", MAX_WORKERS)
    if r2_is_configured():
        R2_CLEANUP_TASK = asyncio.create_task(
            cleanup_loop(
                r2_client,
                R2_BUCKET_NAME,
                prefix="downloads/",
                retention_seconds=R2_OBJECT_RETENTION_SECONDS,
                interval_seconds=R2_CLEANUP_INTERVAL_SECONDS,
            ),
            name="r2-cleanup",
        )
        LOG.info(
            "R2 cleanup enabled: downloads/ retained for %ss, checked every %ss",
            R2_OBJECT_RETENTION_SECONDS,
            R2_CLEANUP_INTERVAL_SECONDS,
        )


async def post_shutdown(application: Application) -> None:
    global R2_CLEANUP_TASK
    if R2_CLEANUP_TASK:
        R2_CLEANUP_TASK.cancel()
        await asyncio.gather(R2_CLEANUP_TASK, return_exceptions=True)
        R2_CLEANUP_TASK = None


def start_admin_api() -> threading.Thread | None:
    if not ADMIN_API_ENABLED or not ADMIN_API_TOKEN:
        LOG.info("Admin API disabled; set ADMIN_API_TOKEN and ADMIN_API_ENABLED=true to enable it")
        return None
    try:
        import uvicorn
        from .bot.admin_api import create_app
    except ImportError:
        import uvicorn
        from bot.admin_api import create_app
    config = uvicorn.Config(create_app(), host=ADMIN_API_HOST, port=ADMIN_API_PORT, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="admin-api", daemon=True)
    thread.start()
    LOG.info("Admin API listening on %s:%s", ADMIN_API_HOST, ADMIN_API_PORT)
    return thread


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN must be set")
    try:
        from .bot import activity_store
    except ImportError:
        from bot import activity_store
    activity_store.initialize()
    start_admin_api()
    builder = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).post_shutdown(post_shutdown)
    if TELEGRAM_API_BASE_URL:
        builder = builder.base_url(TELEGRAM_API_BASE_URL)
    if TELEGRAM_API_FILE_BASE_URL:
        builder = builder.base_file_url(TELEGRAM_API_FILE_BASE_URL)
    application = builder.build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("support", support_command))
    application.add_handler(CommandHandler("download", download_command))
    application.add_handler(CallbackQueryHandler(button_handler, pattern=r"^d\|"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
