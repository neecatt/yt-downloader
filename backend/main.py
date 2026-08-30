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
from pathlib import Path
from typing import Any, Callable
try:
    from .bot.integrations.cookies import prepare_cookie_file as _prepare_cookie_file
    from .bot.platforms.media import display_error, format_duration, progress_text, safe_filename
    from .bot.platforms.routing import activity_platform, is_x_photo_link, should_analyze_media_type
    from .bot.services import downloader, storage
    from .bot.telegram import callbacks, commands, delivery, keyboards, messages
    from .bot.observability import configure_logging, log_timing
    from .bot.integrations.transcription import (
        transcription_is_configured,
    )
    from .bot.queue import enqueue_transcription, queue_is_configured
    from .bot.runtime import DOWNLOAD_LOCKS, LANGUAGE_CACHE, PENDING_DELIVERIES, STATES, SUPPORT_PROMPT_LAST_SHOWN, LinkState, PendingDelivery
    from .bot.platforms.limits import SlidingWindowLimiter
    from .bot.integrations.r2_cleanup import cleanup_loop, schedule_object_delete
    from .bot.platforms.security import (
        extract_url as _extract_url,
        safe_log_error,
        safe_log_url,
        validate_donation_url,
        validate_remote_url,
    )
    from .bot.i18n import language_keyboard, normalize_language, tr
except ImportError:  # Supports running `python main.py` in backend.
    from bot.integrations.cookies import prepare_cookie_file as _prepare_cookie_file
    from bot.platforms.media import display_error, format_duration, progress_text, safe_filename
    from bot.platforms.routing import activity_platform, is_x_photo_link, should_analyze_media_type
    from bot.services import downloader, storage
    from bot.telegram import callbacks, commands, delivery, keyboards, messages
    from bot.observability import configure_logging, log_timing
    from bot.integrations.transcription import (
        transcription_is_configured,
    )
    from bot.queue import enqueue_transcription, queue_is_configured
    from bot.runtime import DOWNLOAD_LOCKS, LANGUAGE_CACHE, PENDING_DELIVERIES, STATES, SUPPORT_PROMPT_LAST_SHOWN, LinkState, PendingDelivery
    from bot.platforms.limits import SlidingWindowLimiter
    from bot.integrations.r2_cleanup import cleanup_loop, schedule_object_delete
    from bot.platforms.security import (
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

try:
    from .bot.config import settings
except ImportError:
    from bot.config import settings

BOT_TOKEN = settings.telegram.token
MAX_UPLOAD_BYTES = settings.telegram.max_upload_bytes
MAX_DOWNLOAD_BYTES = settings.download.max_bytes
MAX_URL_LENGTH = settings.download.max_url_length
STATE_TTL_SECONDS = settings.runtime.state_ttl
PENDING_DELIVERY_TTL_SECONDS = settings.runtime.pending_delivery_ttl
MAX_STATE_ENTRIES = settings.runtime.max_state_entries
MAX_WORKERS = settings.download.workers
FRAGMENT_WORKERS = settings.download.fragment_workers
R2_UPLOAD_CONCURRENCY = settings.storage.upload_concurrency
HTTP_CHUNK_SIZE_MB = settings.download.http_chunk_size_mb
YTDLP_COOKIES_FILE = settings.download.cookies_file
YTDLP_COOKIES_B64 = settings.download.cookies_b64
YTDLP_PROXY = settings.download.proxy
YTDLP_PLAYER_CLIENT = settings.download.player_client
YTDLP_PO_TOKEN = settings.download.po_token
YTDLP_POT_PROVIDER_URL = settings.download.po_provider_url
YTDLP_JS_RUNTIME = settings.download.js_runtime
TELEGRAM_API_BASE_URL = settings.telegram.api_base_url
TELEGRAM_API_FILE_BASE_URL = settings.telegram.api_file_base_url
DELIVERY_MODE = settings.download.delivery_mode
ALLOW_GENERIC_HTTPS = settings.download.allow_generic_https
DONATION_URL_RAW = settings.donation.url
DONATION_PROMPTS_ENABLED = settings.donation.prompts_enabled
DONATION_PROMPT_COOLDOWN_SECONDS = settings.donation.cooldown_seconds

R2_ACCOUNT_ID = settings.storage.account_id
R2_ENDPOINT_URL = settings.storage.endpoint_url
R2_API_TOKEN = settings.storage.api_token
R2_ACCESS_KEY_ID = settings.storage.access_key_id
R2_SECRET_ACCESS_KEY = settings.storage.secret_access_key
R2_BUCKET_NAME = settings.storage.bucket_name
R2_PUBLIC_BASE_URL = settings.storage.public_base_url
R2_PRESIGNED_URL_TTL = settings.storage.presigned_url_ttl
R2_CLEANUP_INTERVAL_SECONDS = settings.storage.cleanup_interval
# Keep object retention tied to the URL lifetime so cleanup cannot leave
# expired downloads stored longer than necessary or delete them prematurely.
R2_OBJECT_RETENTION_SECONDS = R2_PRESIGNED_URL_TTL
ADMIN_API_TOKEN = settings.admin.token
ADMIN_API_ENABLED = settings.admin.enabled
ADMIN_API_HOST = settings.admin.host
ADMIN_API_PORT = settings.admin.port
DOWNLOADS_PER_USER_PER_HOUR = settings.runtime.downloads_per_user_hour
DOWNLOADS_PER_USER_PER_DAY = settings.runtime.downloads_per_user_day
ANALYSES_PER_USER_PER_HOUR = settings.runtime.analyses_per_user_hour
DOWNLOADS_GLOBAL_PER_HOUR = settings.runtime.downloads_global_hour
ANALYSES_GLOBAL_PER_HOUR = settings.runtime.analyses_global_hour

# Telegram callback data is limited to 64 bytes. A random opaque key keeps
# URLs and user input out of callback data and prevents cross-chat reuse.
VIDEO_ONLY_MESSAGE = "This is an image or carousel post. This bot only downloads videos and audio. Please send an individual video link."


DONATION_URL = validate_donation_url(DONATION_URL_RAW)


EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="download")
DOWNLOAD_LIMITER = SlidingWindowLimiter()
ANALYSIS_LIMITER = SlidingWindowLimiter()
def prepare_cookie_file() -> str | None:
    return _prepare_cookie_file(YTDLP_COOKIES_B64, YTDLP_COOKIES_FILE)


YTDLP_EFFECTIVE_COOKIES_FILE = prepare_cookie_file()

DOWNLOADER_CONFIG = downloader.DownloaderConfig(
    max_bytes=MAX_DOWNLOAD_BYTES,
    fragment_workers=FRAGMENT_WORKERS,
    http_chunk_size_mb=HTTP_CHUNK_SIZE_MB,
    cookies_file=YTDLP_EFFECTIVE_COOKIES_FILE,
    proxy=YTDLP_PROXY,
    js_runtime=YTDLP_JS_RUNTIME,
    player_client=YTDLP_PLAYER_CLIENT,
    po_token=YTDLP_PO_TOKEN,
    po_provider_url=YTDLP_POT_PROVIDER_URL,
)


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
            from .bot.persistence import activity_store
        except ImportError:
            from bot.persistence import activity_store
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
            from .bot.persistence import activity_store
        except ImportError:
            from bot.persistence import activity_store
        activity_store.set_language(chat_id, selected)
    except Exception:
        LOG.warning("Could not persist chat language", exc_info=True)
    return selected


def language_for_update(update: Update) -> str:
    return chat_language(update.effective_chat.id)


def start_keyboard(language: str) -> InlineKeyboardMarkup:
    return keyboards.start(language, support_keyboard)


def prune_states() -> None:
    try:
        from .bot.runtime.state import prune_link_states
    except ImportError:
        from bot.runtime.state import prune_link_states
    prune_link_states(ttl_seconds=STATE_TTL_SECONDS, max_entries=MAX_STATE_ENTRIES)


def prune_pending_deliveries() -> None:
    try:
        from .bot.runtime.state import prune_pending_deliveries as expire_pending
    except ImportError:
        from bot.runtime.state import prune_pending_deliveries as expire_pending
    for pending in expire_pending(ttl_seconds=PENDING_DELIVERY_TTL_SECONDS):
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


_activity_platform = activity_platform


def _record_contact(update: Update) -> None:
    try:
        try:
            from .bot.persistence import activity_store
        except ImportError:
            from bot.persistence import activity_store
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
            from .bot.persistence import activity_store
        except ImportError:
            from bot.persistence import activity_store
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
            from .bot.persistence import activity_store
        except ImportError:
            from bot.persistence import activity_store
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
        from .bot.persistence import activity_store
    except ImportError:
        from bot.persistence import activity_store
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
    return keyboards.transcription_fallback(key, language)


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
    return storage.configured(R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME)


def r2_client():
    return storage.client(R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME)


def upload_to_r2(filename: Path, info: dict[str, Any], extension: str) -> str:
    """Upload a completed file and return a temporary browser download URL."""
    url, _ = upload_to_r2_with_key(filename, info, extension)
    return url


def upload_to_r2_with_key(filename: Path, info: dict[str, Any], extension: str) -> tuple[str, str]:
    return storage.upload(
        filename, info, extension, client_factory=r2_client, bucket=R2_BUCKET_NAME,
        public_base_url=R2_PUBLIC_BASE_URL, url_ttl=R2_PRESIGNED_URL_TTL,
        retention_seconds=R2_OBJECT_RETENTION_SECONDS, schedule_delete=schedule_object_delete,
        upload_concurrency=R2_UPLOAD_CONCURRENCY,
    )


def delete_r2_object(object_key: str) -> None:
    if not object_key or not r2_is_configured():
        return
    storage.delete(object_key, client_factory=r2_client, bucket=R2_BUCKET_NAME)


ProgressCallback = downloader.ProgressCallback

# Telegram commands live in bot.telegram.commands; aliases preserve the
# existing registration names and compatibility for external integrations.
start = commands.start
support_command = commands.support
settings_command = commands.settings
language_button_handler = commands.language_button
feedback_command = commands.feedback
help_command = commands.help_command
download_command = commands.download
transcribe_command = commands.transcribe
make_choice = commands.make_choice
send_file = delivery.send_file
send_r2_link = delivery.send_r2_link
run_download_with_progress = delivery.download_with_progress
button_handler = callbacks.handle
handle_message = messages.handle
_run_transcription = messages.run_transcription
delivery_choice_keyboard = keyboards.delivery_choice


# Compatibility wrappers keep the Telegram handlers and tests focused on bot
# orchestration while the yt-dlp implementation lives in its service module.
def ydl_base_options(tmpdir: str, progress_callback: ProgressCallback | None = None) -> dict[str, Any]:
    return downloader.base_options(DOWNLOADER_CONFIG, tmpdir, progress_callback)


def ydl_options(tmpdir: str, fmt: str, progress_callback: ProgressCallback | None = None) -> dict[str, Any]:
    return downloader.format_options(DOWNLOADER_CONFIG, tmpdir, fmt, progress_callback)


def analyze_url(url: str) -> dict[str, Any]:
    LOG.info("event=analysis_started source=%s", safe_log_url(url))
    return downloader.analyze(DOWNLOADER_CONFIG, url, tempfile.gettempdir())


def download_sync(url: str, fmt: str, tmpdir: str, progress_callback: ProgressCallback | None = None) -> tuple[dict[str, Any], Path, str]:
    return downloader.download(DOWNLOADER_CONFIG, url, fmt, tmpdir, progress_callback)



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
        from .bot.api.admin import create_app
    except ImportError:
        import uvicorn
        from bot.api.admin import create_app
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
        from .bot.persistence import activity_store
    except ImportError:
        from bot.persistence import activity_store
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
