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
import shutil
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
    from .bot.observability import configure_logging, log_timing
    from .bot.transcription import (
        format_transcript,
        transcript_filename,
        transcribe_audio_url_sync,
        transcription_is_configured,
    )
    from .bot.limits import SlidingWindowLimiter
    from .bot.r2_cleanup import cleanup_loop, schedule_object_delete
    from .bot.security import (
        extract_url as _extract_url,
        safe_log_error,
        safe_log_url,
        validate_donation_url,
        validate_remote_url,
    )
    from .bot.i18n import language_keyboard, normalize_language, tr
except ImportError:  # Supports running `python main.py` in backend.
    from bot.cookies import prepare_cookie_file as _prepare_cookie_file
    from bot.media import display_error, format_duration, progress_text, safe_filename
    from bot.observability import configure_logging, log_timing
    from bot.transcription import (
        format_transcript,
        transcript_filename,
        transcribe_audio_url_sync,
        transcription_is_configured,
    )
    from bot.limits import SlidingWindowLimiter
    from bot.r2_cleanup import cleanup_loop, schedule_object_delete
    from bot.security import (
        extract_url as _extract_url,
        safe_log_error,
        safe_log_url,
        validate_donation_url,
        validate_remote_url,
    )
    from bot.i18n import language_keyboard, normalize_language, tr
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
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
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
configure_logging()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MAX_UPLOAD_BYTES = min(4096, max(1, int(os.getenv("TELEGRAM_MAX_UPLOAD_MB", "49")))) * 1024 * 1024
MAX_DOWNLOAD_BYTES = min(4096, max(1, int(os.getenv("MAX_DOWNLOAD_MB", "2048")))) * 1024 * 1024
MAX_URL_LENGTH = max(256, int(os.getenv("MAX_URL_LENGTH", "4096")))
STATE_TTL_SECONDS = min(86400, max(60, int(os.getenv("CALLBACK_STATE_TTL_SECONDS", "1800"))))
PENDING_DELIVERY_TTL_SECONDS = min(3600, max(60, int(os.getenv("PENDING_DELIVERY_TTL_SECONDS", "900"))))
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
    "x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com",
    "linkedin.com", "www.linkedin.com", "lnkd.in",
}
IMAGE_POST_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif", "avif"}
VIDEO_ONLY_MESSAGE = "This is an image or carousel post. This bot only downloads videos and audio. Please send an individual video link."


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


@dataclass(slots=True)
class PendingDelivery:
    directory: Path
    filename: Path
    chat_id: int
    user_id: int
    info: dict[str, Any]
    extension: str
    fmt: str
    size_bytes: int
    activity_id: str | None
    created_at: float


STATES: dict[str, LinkState] = {}
PENDING_DELIVERIES: dict[str, PendingDelivery] = {}
LANGUAGE_CACHE: dict[int, str] = {}
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


def chat_language(chat_id: int) -> str:
    cached = LANGUAGE_CACHE.get(chat_id)
    if cached:
        return normalize_language(cached)
    try:
        try:
            from .bot import activity_store
        except ImportError:
            from bot import activity_store
        selected = normalize_language(activity_store.get_language(chat_id))
    except Exception:
        selected = "en"
    LANGUAGE_CACHE[chat_id] = selected
    return selected


def update_chat_language(chat_id: int, language: str) -> str:
    selected = normalize_language(language)
    LANGUAGE_CACHE[chat_id] = selected
    try:
        try:
            from .bot import activity_store
        except ImportError:
            from bot import activity_store
        activity_store.set_language(chat_id, selected)
    except Exception:
        LOG.warning("Could not persist chat language", exc_info=True)
    return selected


def language_for_update(update: Update) -> str:
    return chat_language(update.effective_chat.id)


def start_keyboard(language: str) -> InlineKeyboardMarkup:
    rows = list(language_keyboard().inline_keyboard)
    support = support_keyboard(language)
    if support:
        rows.extend(support.inline_keyboard)
    return InlineKeyboardMarkup(rows)


def prune_states() -> None:
    cutoff = time.monotonic() - STATE_TTL_SECONDS
    for key, state in list(STATES.items()):
        if state.created_at < cutoff:
            STATES.pop(key, None)
    if len(STATES) > MAX_STATE_ENTRIES:
        excess = len(STATES) - MAX_STATE_ENTRIES
        for key, _ in sorted(STATES.items(), key=lambda item: item[1].created_at)[:excess]:
            STATES.pop(key, None)


def prune_pending_deliveries() -> None:
    cutoff = time.monotonic() - PENDING_DELIVERY_TTL_SECONDS
    for key, pending in list(PENDING_DELIVERIES.items()):
        if pending.created_at < cutoff:
            PENDING_DELIVERIES.pop(key, None)
            shutil.rmtree(pending.directory, ignore_errors=True)


def save_pending_delivery(
    *, filename: Path, directory: Path, update: Update, info: dict[str, Any],
    extension: str, fmt: str, size_bytes: int, activity_id: str | None,
) -> str:
    prune_pending_deliveries()
    user = update.effective_user
    key = secrets.token_urlsafe(9)
    PENDING_DELIVERIES[key] = PendingDelivery(
        directory=directory,
        filename=filename,
        chat_id=update.effective_chat.id,
        user_id=user.id if user else 0,
        info=info,
        extension=extension,
        fmt=fmt,
        size_bytes=size_bytes,
        activity_id=activity_id,
        created_at=time.monotonic(),
    )
    return key


def take_pending_delivery(key: str, update: Update) -> PendingDelivery | None:
    prune_pending_deliveries()
    pending = PENDING_DELIVERIES.get(key)
    if not pending or pending.chat_id != update.effective_chat.id:
        return None
    user = update.effective_user
    if pending.user_id and user and pending.user_id != user.id:
        return None
    PENDING_DELIVERIES.pop(key, None)
    return pending


def discard_pending_delivery(pending: PendingDelivery) -> None:
    shutil.rmtree(pending.directory, ignore_errors=True)


def save_state(update: Update, url: str, info: dict[str, Any] | None = None) -> str:
    prune_states()
    message = update.effective_message
    user = update.effective_user
    key = secrets.token_urlsafe(9)
    _record_contact(update)
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
    if "twitter" in host or host == "x.com": return "x"
    if "linkedin" in host or host == "lnkd.in": return "linkedin"
    return "other"


def is_image_or_carousel_info(info: dict[str, Any] | None) -> bool:
    if not info:
        return False
    extension = str(info.get("ext") or "").lower()
    if extension in IMAGE_POST_EXTENSIONS:
        return True
    formats = info.get("formats") or []
    valid_formats = [item for item in formats if isinstance(item, dict)]
    return bool(valid_formats) and all(
        str(item.get("ext") or "").lower() in IMAGE_POST_EXTENSIONS
        for item in valid_formats
    )


def is_x_photo_link(url: str) -> bool:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    return host in {"x.com", "twitter.com", "mobile.twitter.com"} and "/photo/" in parsed.path.lower()


def should_analyze_media_type(url: str) -> bool:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path = parsed.path.lower()
    if is_x_photo_link(url):
        return True
    return (
        host == "instagram.com" and ("/p/" in path or "/reel/" in path or "/tv/" in path)
    ) or (host == "linkedin.com" and "/posts/" in path) or (
        host in {"facebook.com", "m.facebook.com", "web.facebook.com"}
        and any(marker in path for marker in ("/posts/", "/photos/", "/photo.php", "/permalink/"))
    )


def _record_contact(update: Update) -> None:
    try:
        try:
            from .bot import activity_store
        except ImportError:
            from bot import activity_store
        if not activity_store.enabled() or not update.effective_chat:
            return
        user = update.effective_user
        chat = update.effective_chat
        activity_store.record_contact(
            chat_id=chat.id,
            username=f"@{getattr(user, 'username', '')}" if getattr(user, "username", None) else None,
            display_name=getattr(user, "full_name", None) if user else None,
            chat_type=getattr(chat, "type", None),
        )
    except Exception:
        LOG.warning("Could not record bot contact", exc_info=True)


def _record_chat_message(update: Update, text: str) -> None:
    if not text.strip() or not update.effective_chat:
        return
    try:
        try:
            from .bot import activity_store
        except ImportError:
            from bot import activity_store
        user = update.effective_user
        message = update.effective_message
        activity_store.record_message(
            chat_id=update.effective_chat.id,
            username=f"@{getattr(user, 'username', '')}" if getattr(user, "username", None) else None,
            display_name=getattr(user, "full_name", None) if user else None,
            direction="inbound",
            text=text,
            telegram_message_id=getattr(message, "message_id", None),
        )
    except Exception:
        LOG.warning("Could not record incoming chat message", exc_info=True)


def _create_activity_event(update: Update, url: str, info: dict[str, Any] | None, *, action: str = "download") -> str | None:
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
            chat_id=getattr(chat, "id", None) if chat else None,
            source_url=url,
            title=(info or {}).get("title"),
            platform=_activity_platform(url),
            action=action,
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


def support_keyboard(language: str = "en") -> InlineKeyboardMarkup | None:
    if not support_is_configured():
        return None
    buttons = [InlineKeyboardButton(tr(language, "support_button"), url=DONATION_URL)]
    return InlineKeyboardMarkup([buttons])


def transcription_fallback_keyboard(key: str, language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(tr(language, "transcribe"), callback_data=f"t|{key}")]])


def should_offer_transcription_fallback(exc: Exception) -> bool:
    """Offer the alternate path only for source-access checks, not private/media errors."""
    message = str(exc).lower()
    return any(marker in message for marker in ("access check", "not a bot", "sign in to confirm", "po token"))


async def send_support_prompt(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int, *, force: bool = False, language: str | None = None) -> bool:
    if not force and not support_prompt_allowed(chat_id, user_id):
        return False
    selected_language = normalize_language(language or chat_language(chat_id))
    markup = support_keyboard(selected_language)
    if not markup:
        return False
    await context.bot.send_message(
        chat_id=chat_id,
        text=tr(selected_language, "support"),
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
    url, _ = upload_to_r2_with_key(filename, info, extension)
    return url


def upload_to_r2_with_key(filename: Path, info: dict[str, Any], extension: str) -> tuple[str, str]:
    """Upload a file and return its temporary URL plus object key."""
    started = time.perf_counter()
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
        ExtraArgs={"ContentType": {"mp3": "audio/mpeg", "mp4": "video/mp4"}.get(extension, "application/octet-stream")},
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
    url = client.generate_presigned_url(
        "get_object",
        Params={"Bucket": R2_BUCKET_NAME, "Key": object_key, "ResponseContentDisposition": f'attachment; filename="{download_name}"'},
        ExpiresIn=R2_PRESIGNED_URL_TTL,
    )
    log_timing(LOG, "r2_upload_finished", started, size_bytes=filename.stat().st_size, extension=extension)
    return url, object_key


def delete_r2_object(object_key: str) -> None:
    if not object_key or not r2_is_configured():
        return
    started = time.perf_counter()
    try:
        r2_client().delete_object(Bucket=R2_BUCKET_NAME, Key=object_key)
        log_timing(LOG, "r2_transcription_cleanup_finished", started)
    except Exception:
        LOG.warning("Could not immediately delete temporary transcription object", exc_info=True)


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
    started = time.perf_counter()
    LOG.info("event=analysis_started source=%s", safe_log_url(url))
    validate_remote_url(url)
    options = ydl_base_options(tempfile.gettempdir())
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


def download_sync(url: str, fmt: str, tmpdir: str, progress_callback: ProgressCallback | None = None) -> tuple[dict[str, Any], Path, str]:
    started = time.perf_counter()
    validate_remote_url(url)
    LOG.info("event=download_started source=%s format=%s", safe_log_url(url), fmt)
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
            extension = "mp3" if fmt.startswith("mp3") else filename.suffix.lstrip(".").lower() or "mp4"
            log_timing(LOG, "download_finished", started, source=safe_log_url(url), format=fmt, size_bytes=filename.stat().st_size)
            return info, filename, extension
        except Exception as exc:
            LOG.warning("event=download_attempt_failed attempt=%s format=%s error=%s", attempt + 1, fmt, safe_log_error(exc))
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
    _record_contact(update)
    language = language_for_update(update)
    await update.effective_message.reply_text(
        f"{tr(language, 'welcome')}\n\n{tr(language, 'help_hint')}\n{tr(language, 'settings_hint')}",
        reply_markup=start_keyboard(language),
    )


async def support_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _record_contact(update)
    language = language_for_update(update)
    if not support_is_configured():
        await update.effective_message.reply_text(tr(language, "support_unconfigured"))
        return
    await send_support_prompt(context, update.effective_chat.id, update.effective_user.id, force=True, language=language)


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _record_contact(update)
    language = language_for_update(update)
    await update.effective_message.reply_text(
        tr(language, "settings_language"),
        reply_markup=language_keyboard(),
    )


async def language_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, language: str) -> None:
    selected = update_chat_language(update.effective_chat.id, language)
    await update.callback_query.edit_message_text(
        f"{tr(selected, 'welcome')}\n\n{tr(selected, 'help_hint')}\n{tr(selected, 'settings_hint')}",
        reply_markup=start_keyboard(selected),
    )


async def feedback_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _record_contact(update)
    language = language_for_update(update)
    feedback = " ".join(context.args).strip()
    if not feedback:
        await update.effective_message.reply_text(tr(language, "feedback_usage"))
        return
    if len(feedback) > 4096:
        await update.effective_message.reply_text(tr(language, "feedback_too_long"))
        return
    try:
        try:
            from .bot import activity_store
        except ImportError:
            from bot import activity_store
        user = update.effective_user
        chat = update.effective_chat
        feedback_id = activity_store.create_feedback(
            chat_id=chat.id,
            username=f"@{getattr(user, 'username', '')}" if getattr(user, "username", None) else None,
            display_name=getattr(user, "full_name", None) if user else None,
            feedback=feedback,
        )
    except Exception:
        feedback_id = None
        LOG.warning("Could not save user feedback", exc_info=True)
    if feedback_id:
        await update.effective_message.reply_text(tr(language, "feedback_saved"))
    else:
        await update.effective_message.reply_text(tr(language, "feedback_failed"))


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _record_contact(update)
    language = language_for_update(update)
    await update.effective_message.reply_text(f"{tr(language, 'help')}\n\n{tr(language, 'transcription_help')}")


async def make_choice(update: Update, url: str, info: dict[str, Any] | None = None) -> None:
    key = save_state(update, url, info)
    language = language_for_update(update)
    title = (info or {}).get("title", "Video")
    duration = (info or {}).get("duration")
    duration_line = f"\n⏱ {tr(language, 'duration')}: {format_duration(duration)}" if duration else ""
    keyboard = [
        [InlineKeyboardButton(tr(language, "fast_360"), callback_data=f"d|360p|{key}"), InlineKeyboardButton(tr(language, "quality_480"), callback_data=f"d|480p|{key}")],
        [InlineKeyboardButton(tr(language, "quality_720"), callback_data=f"d|720p|{key}"), InlineKeyboardButton(tr(language, "quality_1080"), callback_data=f"d|1080p|{key}")],
        [InlineKeyboardButton(tr(language, "best"), callback_data=f"d|best|{key}")],
        [InlineKeyboardButton(tr(language, "mp3_128"), callback_data=f"d|mp3_128|{key}"), InlineKeyboardButton(tr(language, "mp3_192"), callback_data=f"d|mp3_192|{key}")],
        [InlineKeyboardButton(tr(language, "mp3_320"), callback_data=f"d|mp3_320|{key}")],
        [InlineKeyboardButton(tr(language, "transcribe"), callback_data=f"t|{key}")],
    ]
    await update.effective_message.reply_text(
        tr(language, "choose_format", title=title, duration=duration_line),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def download_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _record_contact(update)
    language = language_for_update(update)
    if not context.args:
        await update.effective_message.reply_text(tr(language, "download_usage"))
        return
    url = extract_url(context.args[0], any_https=ALLOW_GENERIC_HTTPS)
    if not url:
        await update.effective_message.reply_text(tr(language, "download_url"))
        return
    user_id = update.effective_user.id if update.effective_user else 0
    if not allow_analysis(user_id):
        await update.effective_message.reply_text(tr(language, "analysis_limit"))
        return
    status = await update.effective_message.reply_text(tr(language, "analyzing"))
    try:
        info = await asyncio.get_running_loop().run_in_executor(EXECUTOR, analyze_url, url)
        await status.delete()
        await make_choice(update, url, info)
    except Exception as exc:
        LOG.info("analysis failed for %s: %s", safe_log_url(url), safe_log_error(exc))
        if should_offer_transcription_fallback(exc) and transcription_is_configured() and r2_is_configured():
            key = save_state(update, url)
            await status.edit_text(
                f"{display_error(exc, language)}\n\n{tr(language, 'transcription_fallback')}",
                reply_markup=transcription_fallback_keyboard(key, language),
            )
        else:
            await status.edit_text(display_error(exc, language))


async def transcribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Transcribe a link directly, without making the user choose a download format."""
    _record_contact(update)
    language = language_for_update(update)
    if not context.args:
        await update.effective_message.reply_text(tr(language, "transcribe_usage"))
        return
    url = extract_url(context.args[0], any_https=ALLOW_GENERIC_HTTPS)
    if not url:
        await update.effective_message.reply_text(tr(language, "transcribe_url"))
        return
    if not transcription_is_configured():
        await update.effective_message.reply_text(tr(language, "transcription_unavailable"))
        return
    if not r2_is_configured():
        await update.effective_message.reply_text(tr(language, "transcription_storage"))
        return
    user_id = update.effective_user.id if update.effective_user else 0
    if not allow_analysis(user_id):
        await update.effective_message.reply_text(tr(language, "analysis_limit"))
        return
    status = await update.effective_message.reply_text(tr(language, "transcription_starting"))
    activity_id = _create_activity_event(update, url, None, action="transcribe")
    await _run_transcription(update, status, url, language, activity_id=activity_id)


async def _run_transcription(update: Update, status: Any, url: str, language: str, *, activity_id: str | None = None) -> None:
    """Run Modal in the existing worker pool and deliver a transcript artifact."""
    async def edit(text: str) -> None:
        method = getattr(status, "edit_message_text", None) or getattr(status, "edit_text")
        await method(text)

    async def remove() -> None:
        method = getattr(status, "delete_message", None) or getattr(status, "delete")
        await method()

    directory = Path(tempfile.mkdtemp(prefix="transcription-"))
    object_key: str | None = None
    transcription_started = time.perf_counter()
    try:
        await edit(tr(language, "downloading", fmt="mp3"))
        download_started = time.perf_counter()
        info, audio_file, _ = await asyncio.get_running_loop().run_in_executor(
            EXECUTOR, download_sync, url, "mp3", str(directory)
        )
        LOG.info("transcription stage=railway_audio_download seconds=%.2f", time.perf_counter() - download_started)
        await edit(tr(language, "transcription_processing"))
        upload_started = time.perf_counter()
        audio_url, object_key = await asyncio.get_running_loop().run_in_executor(
            EXECUTOR, upload_to_r2_with_key, audio_file, info, "mp3"
        )
        LOG.info("transcription stage=r2_upload seconds=%.2f", time.perf_counter() - upload_started)
        modal_started = time.perf_counter()
        result = await asyncio.get_running_loop().run_in_executor(
            EXECUTOR,
            transcribe_audio_url_sync,
            audio_url,
            str(info.get("title") or "Transcript"),
            info.get("duration"),
        )
        LOG.info("transcription stage=modal_total seconds=%.2f total_seconds=%.2f", time.perf_counter() - modal_started, time.perf_counter() - transcription_started)
        transcript = format_transcript(result)
        filename = transcript_filename(str(result.get("title") or "transcript"))
        await remove()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", encoding="utf-8", delete=False) as artifact:
            artifact.write(transcript)
            artifact_path = Path(artifact.name)
        try:
            with artifact_path.open("rb") as document:
                await update.effective_message.reply_document(
                    document=document,
                    filename=filename,
                    caption=tr(language, "transcription_ready", detected_language=result.get("language", "unknown")),
                    read_timeout=120,
                    write_timeout=120,
                )
            _update_activity(
                activity_id,
                status="completed",
                action="transcribe",
                title=result.get("title"),
                duration_ms=int(float(result.get("duration") or 0) * 1000) if result.get("duration") else None,
            )
        finally:
            artifact_path.unlink(missing_ok=True)
    except Exception as exc:
        LOG.info("transcription failed for %s: %s", safe_log_url(url), safe_log_error(exc))
        _update_activity(activity_id, status="failed", action="transcribe", error=display_error(exc, language))
        await edit(display_error(exc, language))
    finally:
        if object_key:
            await asyncio.get_running_loop().run_in_executor(EXECUTOR, delete_r2_object, object_key)
        shutil.rmtree(directory, ignore_errors=True)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _record_contact(update)
    language = language_for_update(update)
    text = update.effective_message.text or ""
    _record_chat_message(update, text)
    url = extract_url(text)
    if not url:
        await update.effective_message.reply_text(tr(language, "invalid_link"))
        return
    if is_x_photo_link(url):
        await update.effective_message.reply_text(tr(language, "video_only"))
        return
    if should_analyze_media_type(url):
        user_id = update.effective_user.id if update.effective_user else 0
        if not allow_analysis(user_id):
            await update.effective_message.reply_text(tr(language, "analysis_limit"))
            return
        status = await update.effective_message.reply_text(tr(language, "checking"))
        try:
            info = await asyncio.get_running_loop().run_in_executor(EXECUTOR, analyze_url, url)
            await status.delete()
            await make_choice(update, url, info)
        except Exception as exc:
            LOG.info("media-type analysis failed for %s: %s", safe_log_url(url), safe_log_error(exc))
            if should_offer_transcription_fallback(exc) and transcription_is_configured() and r2_is_configured():
                key = save_state(update, url)
                await status.edit_text(
                    f"{display_error(exc, language)}\n\n{tr(language, 'transcription_fallback')}",
                    reply_markup=transcription_fallback_keyboard(key, language),
                )
            else:
                await status.edit_text(display_error(exc, language))
        return
    await make_choice(update, url)


async def send_file(context: ContextTypes.DEFAULT_TYPE, chat_id: int, filename: Path, info: dict[str, Any], extension: str, fmt: str) -> None:
    started = time.perf_counter()
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
    log_timing(LOG, "telegram_delivery_finished", started, chat_id=chat_id, size_bytes=size, extension=extension)


async def send_r2_link(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    url: str,
    info: dict[str, Any],
    fmt: str,
    size_bytes: int | None = None,
    reply_markup: InlineKeyboardMarkup | None = None,
    selected_by_user: bool = False,
) -> None:
    language = chat_language(chat_id)
    title = info.get("title", "Downloaded file")
    size_text = f"{size_bytes / 1024 / 1024:.1f} MB" if size_bytes else "large"
    download_button = [InlineKeyboardButton(tr(language, "download_file"), url=url)]
    keyboard_rows = [download_button]
    if reply_markup:
        keyboard_rows.extend(reply_markup.inline_keyboard)
    keyboard = InlineKeyboardMarkup(keyboard_rows)
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"✅ Ready: {title[:700]}\n{tr(language, 'format_label')}: {fmt}\n{tr(language, 'size_label')}: {size_text}\n\n"
            + tr(language, "ready_link_choice" if selected_by_user else "ready_link_large")
        ),
        reply_markup=keyboard,
    )


def delivery_choice_keyboard(key: str, language: str = "en") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(tr(language, "choice_telegram"), callback_data=f"p|telegram|{key}")],
        [InlineKeyboardButton(tr(language, "choice_link"), callback_data=f"p|r2|{key}")],
    ])


async def run_download_with_progress(
    loop: asyncio.AbstractEventLoop,
    url: str,
    fmt: str,
    tmpdir: str,
    query: Any,
    language: str = "en",
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
                await query.edit_message_text(progress_text(latest, fmt, language))
                last_update = now
            except TelegramError:
                LOG.debug("Unable to update download progress", exc_info=True)
    result = await download_task
    while not progress_queue.empty():
        latest = progress_queue.get_nowait()
    if latest and latest.get("status") == "finished":
        try:
            await query.edit_message_text(progress_text(latest, fmt, language))
        except TelegramError:
            LOG.debug("Unable to update final download progress", exc_info=True)
    return result


async def pending_delivery_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str, key: str) -> None:
    query = update.callback_query
    language = language_for_update(update)
    if mode == "r2" and not r2_is_configured():
        await query.edit_message_text(tr(language, "link_unconfigured"))
        return
    pending = take_pending_delivery(key, update)
    if not pending:
        await query.edit_message_text(tr(language, "delivery_expired"))
        return
    lock = DOWNLOAD_LOCKS.setdefault(pending.chat_id, asyncio.Lock())
    delivery_started = time.perf_counter()
    LOG.info("event=delivery_job_started chat_id=%s mode=%s", pending.chat_id, mode)
    try:
        async with lock:
            loop = asyncio.get_running_loop()
            if mode == "telegram":
                await query.edit_message_text(tr(language, "upload_telegram"))
                await send_file(context, pending.chat_id, pending.filename, pending.info, pending.extension, pending.fmt)
                await send_support_prompt(context, pending.chat_id, pending.user_id)
                delivery = "telegram"
            else:
                await query.edit_message_text(tr(language, "prepare_link"))
                download_url = await loop.run_in_executor(
                    EXECUTOR, upload_to_r2, pending.filename, pending.info, pending.extension
                )
                offer_support = support_prompt_allowed(pending.chat_id, pending.user_id)
                await send_r2_link(
                    context, pending.chat_id, download_url, pending.info, pending.fmt,
                    pending.size_bytes, support_keyboard(language) if offer_support else None,
                    selected_by_user=True,
                )
                if offer_support:
                    mark_support_prompt_shown(pending.chat_id, pending.user_id)
                delivery = "r2"
            _update_activity(
                pending.activity_id,
                status="completed",
                fmt=pending.fmt,
                delivery=delivery,
                size_bytes=pending.size_bytes,
                duration_ms=int(pending.info.get("duration", 0) * 1000) if pending.info.get("duration") else None,
                title=pending.info.get("title"),
            )
            await query.delete_message()
    except (TelegramError, BadRequest):
        LOG.exception("Pending delivery failed for chat %s", pending.chat_id)
        _update_activity(pending.activity_id, status="failed", error="Telegram could not accept the file")
        await query.edit_message_text(tr(language, "telegram_failed_other"))
    except Exception as exc:
        LOG.info("pending delivery failed: %s", safe_log_error(exc))
        _update_activity(pending.activity_id, status="failed", error=display_error(exc, language))
        await query.edit_message_text(f"❌ {display_error(exc, language)}")
    finally:
        discard_pending_delivery(pending)
        log_timing(LOG, "delivery_job_finished", delivery_started, chat_id=pending.chat_id, mode=mode)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if isinstance(query.data, str) and query.data.startswith("lang|"):
        _, language = query.data.split("|", 1)
        await language_button_handler(update, context, language)
        return
    if isinstance(query.data, str) and query.data.startswith("t|"):
        _, key = query.data.split("|", 1)
        language = language_for_update(update)
        state = get_state(key, update)
        if not state:
            await query.edit_message_text(tr(language, "link_expired"))
            return
        if not transcription_is_configured():
            await query.edit_message_text(tr(language, "transcription_unavailable"))
            return
        if not r2_is_configured():
            await query.edit_message_text(tr(language, "transcription_storage"))
            return
        if not allow_analysis(state.user_id):
            await query.edit_message_text(tr(language, "analysis_limit"))
            return
        _update_activity(state.activity_id, status="started", action="transcribe")
        await _run_transcription(update, query, state.url, language, activity_id=state.activity_id)
        STATES.pop(key, None)
        return
    try:
        action, value, key = query.data.split("|", 2)
    except (AttributeError, ValueError):
        await query.edit_message_text(tr(language_for_update(update), "invalid_button"))
        return
    if action == "p":
        await pending_delivery_handler(update, context, value, key)
        return
    if action != "d":
        await query.edit_message_text(tr(language_for_update(update), "invalid_button"))
        return
    fmt = value
    state = get_state(key, update)
    language = language_for_update(update)
    if not state:
        await query.edit_message_text(tr(language, "link_expired"))
        return
    lock = DOWNLOAD_LOCKS.setdefault(state.chat_id, asyncio.Lock())
    if lock.locked():
        await query.edit_message_text(tr(language, "already_running"))
        return
    job_started = time.perf_counter()
    LOG.info(
        "event=download_job_started chat_id=%s source=%s format=%s",
        state.chat_id,
        safe_log_url(state.url),
        fmt,
    )
    async with lock:
        if not allow_download(state.user_id):
            await query.edit_message_text(tr(language, "download_limit"))
            return
        await query.edit_message_text(tr(language, "downloading", fmt=fmt))
        await context.bot.send_chat_action(chat_id=state.chat_id, action=ChatAction.UPLOAD_DOCUMENT)
        download_directory = Path(tempfile.mkdtemp(prefix="ytbot-"))
        keep_pending = False
        try:
            loop = asyncio.get_running_loop()
            info, filename, extension = await run_download_with_progress(loop, state.url, fmt, str(download_directory), query, language)
            file_size = filename.stat().st_size
            delivery = None
            if DELIVERY_MODE == "r2":
                await query.edit_message_text(tr(language, "upload_cloud"))
                download_url = await loop.run_in_executor(EXECUTOR, upload_to_r2, filename, info, extension)
                offer_support = support_prompt_allowed(state.chat_id, state.user_id)
                await send_r2_link(context, state.chat_id, download_url, info, fmt, file_size, support_keyboard(language) if offer_support else None)
                if offer_support:
                    mark_support_prompt_shown(state.chat_id, state.user_id)
                delivery = "r2"
            elif DELIVERY_MODE == "auto" and file_size > MAX_UPLOAD_BYTES and r2_is_configured():
                await query.edit_message_text(tr(language, "upload_cloud"))
                download_url = await loop.run_in_executor(EXECUTOR, upload_to_r2, filename, info, extension)
                offer_support = support_prompt_allowed(state.chat_id, state.user_id)
                await send_r2_link(context, state.chat_id, download_url, info, fmt, file_size, support_keyboard(language) if offer_support else None)
                if offer_support:
                    mark_support_prompt_shown(state.chat_id, state.user_id)
                delivery = "r2"
            elif DELIVERY_MODE == "auto" and file_size <= MAX_UPLOAD_BYTES and r2_is_configured():
                pending_key = save_pending_delivery(
                    filename=filename, directory=download_directory, update=update, info=info,
                    extension=extension, fmt=fmt, size_bytes=file_size, activity_id=state.activity_id,
                )
                keep_pending = True
                await query.edit_message_text(
                    tr(language, "ready_choice", title=info.get("title", "Downloaded file")[:700], size=file_size / 1024 / 1024),
                    reply_markup=delivery_choice_keyboard(pending_key, language),
                )
                return
            elif file_size <= MAX_UPLOAD_BYTES:
                await query.edit_message_text(tr(language, "upload_telegram"))
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
            await query.edit_message_text(tr(language, "telegram_failed_quality"))
        except Exception as exc:
            LOG.info("download failed for %s: %s", safe_log_url(state.url), safe_log_error(exc))
            _update_activity(state.activity_id, status="failed", error=display_error(exc, language))
            await query.edit_message_text(f"❌ {display_error(exc, language)}")
        finally:
            if not keep_pending:
                shutil.rmtree(download_directory, ignore_errors=True)
            STATES.pop(key, None)
            log_timing(
                LOG,
                "download_job_finished",
                job_started,
                chat_id=state.chat_id,
                format=fmt,
                source=safe_log_url(state.url),
            )


R2_CLEANUP_TASK: asyncio.Task[Any] | None = None
PENDING_DELIVERY_CLEANUP_TASK: asyncio.Task[Any] | None = None


async def pending_delivery_cleanup_loop() -> None:
    interval = min(60, max(30, PENDING_DELIVERY_TTL_SECONDS // 3))
    while True:
        prune_pending_deliveries()
        await asyncio.sleep(interval)


async def post_init(application: Application) -> None:
    global R2_CLEANUP_TASK, PENDING_DELIVERY_CLEANUP_TASK
    LOG.info("Bot started with %s download worker(s)", MAX_WORKERS)
    await application.bot.set_my_commands([
        BotCommand("start", "Show the welcome screen"),
        BotCommand("help", "Show usage instructions"),
        BotCommand("download", "Download a video from a link"),
        BotCommand("transcribe", "Transcribe speech from a video link"),
        BotCommand("feedback", "Send feedback"),
        BotCommand("support", "Support the bot"),
        BotCommand("settings", "Change language"),
    ])
    PENDING_DELIVERY_CLEANUP_TASK = asyncio.create_task(
        pending_delivery_cleanup_loop(), name="pending-delivery-cleanup"
    )
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
    global R2_CLEANUP_TASK, PENDING_DELIVERY_CLEANUP_TASK
    tasks = [task for task in (R2_CLEANUP_TASK, PENDING_DELIVERY_CLEANUP_TASK) if task]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    R2_CLEANUP_TASK = None
    PENDING_DELIVERY_CLEANUP_TASK = None
    for pending in list(PENDING_DELIVERIES.values()):
        discard_pending_delivery(pending)
    PENDING_DELIVERIES.clear()


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
    LOG.info(
        "event=application_starting delivery_mode=%s max_workers=%s max_download_mb=%s telegram_limit_mb=%s r2_configured=%s admin_api=%s",
        DELIVERY_MODE, MAX_WORKERS, MAX_DOWNLOAD_BYTES // (1024 * 1024),
        MAX_UPLOAD_BYTES // (1024 * 1024), r2_is_configured(), bool(ADMIN_API_TOKEN and ADMIN_API_ENABLED),
    )
    builder = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).post_shutdown(post_shutdown)
    if TELEGRAM_API_BASE_URL:
        builder = builder.base_url(TELEGRAM_API_BASE_URL)
    if TELEGRAM_API_FILE_BASE_URL:
        builder = builder.base_file_url(TELEGRAM_API_FILE_BASE_URL)
    application = builder.build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("support", support_command))
    application.add_handler(CommandHandler("feedback", feedback_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("settings", settings_command))
    application.add_handler(CommandHandler("download", download_command))
    application.add_handler(CommandHandler("transcribe", transcribe_command))
    application.add_handler(CallbackQueryHandler(button_handler, pattern=r"^(?:d|p|t|lang)\|"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    LOG.info("event=telegram_polling_start")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
