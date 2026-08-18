"""Telegram video downloader bot.

The bot keeps only short-lived callback state in memory. Downloads run in a
thread pool because yt-dlp and ffmpeg are blocking processes; Telegram API
calls remain asynchronous.
"""

from __future__ import annotations

import asyncio
import base64
import concurrent.futures
import ipaddress
import logging
import os
import re
import secrets
import socket
import tempfile
import time
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse, urlsplit, urlunsplit

import yt_dlp
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

LOG = logging.getLogger("yt_downloader_bot")

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MAX_UPLOAD_BYTES = int(os.getenv("TELEGRAM_MAX_UPLOAD_MB", "49")) * 1024 * 1024
MAX_DOWNLOAD_BYTES = int(os.getenv("MAX_DOWNLOAD_MB", "2048")) * 1024 * 1024
MAX_URL_LENGTH = max(256, int(os.getenv("MAX_URL_LENGTH", "4096")))
STATE_TTL_SECONDS = int(os.getenv("CALLBACK_STATE_TTL_SECONDS", "1800"))
MAX_STATE_ENTRIES = max(100, int(os.getenv("MAX_STATE_ENTRIES", "10000")))
MAX_WORKERS = max(1, int(os.getenv("DOWNLOAD_WORKERS", "2")))
FRAGMENT_WORKERS = max(1, int(os.getenv("FRAGMENT_WORKERS", "4")))
R2_UPLOAD_CONCURRENCY = max(1, int(os.getenv("R2_UPLOAD_CONCURRENCY", "8")))
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
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID")
R2_ENDPOINT_URL = os.getenv("R2_ENDPOINT_URL") or (f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com" if R2_ACCOUNT_ID else None)
R2_API_TOKEN = os.getenv("R2_API_TOKEN")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
if R2_API_TOKEN and ":" in R2_API_TOKEN:
    R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY = R2_API_TOKEN.split(":", 1)
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME")
R2_PUBLIC_BASE_URL = os.getenv("R2_PUBLIC_BASE_URL")
R2_PRESIGNED_URL_TTL = max(60, int(os.getenv("R2_PRESIGNED_URL_TTL_SECONDS", "86400")))

# Telegram callback data is limited to 64 bytes. A random opaque key keeps
# URLs and user input out of callback data and prevents cross-chat reuse.
URL_RE = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
SUPPORTED_CHAT_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be",
    "tiktok.com", "www.tiktok.com", "vm.tiktok.com", "vt.tiktok.com",
    "instagram.com", "www.instagram.com",
}


@dataclass(slots=True)
class LinkState:
    url: str
    chat_id: int
    user_id: int
    created_at: float
    title: str = "Video"
    duration: int | None = None


STATES: dict[str, LinkState] = {}
DOWNLOAD_LOCKS: dict[int, asyncio.Lock] = {}
EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="download")
ProgressCallback = Callable[[dict[str, Any]], None]


def prepare_cookie_file() -> str | None:
    """Materialize optional Netscape cookies from a deployment secret."""
    if not YTDLP_COOKIES_B64:
        return YTDLP_COOKIES_FILE
    try:
        # Railway values are sometimes pasted with visual line wrapping.
        # Whitespace is not part of base64, so remove it before decoding.
        encoded = b"".join(YTDLP_COOKIES_B64.encode("ascii").split())
        cookie_data = base64.b64decode(encoded, validate=True)
        if not cookie_data.startswith((b"# HTTP Cookie File", b"# Netscape HTTP Cookie File")):
            raise ValueError("cookie data is not in Netscape format")
    except (ValueError, base64.binascii.Error) as exc:
        raise RuntimeError("YTDLP_COOKIES_B64 must be valid base64 Netscape cookies") from exc
    fd, cookie_name = tempfile.mkstemp(prefix="yt-dlp-cookies-", suffix=".txt")
    cookie_path = Path(cookie_name)
    with os.fdopen(fd, "wb") as cookie_file:
        cookie_file.write(cookie_data)
    cookie_path.chmod(0o600)
    return str(cookie_path)


YTDLP_EFFECTIVE_COOKIES_FILE = prepare_cookie_file()


def extract_url(text: str, *, any_https: bool = False) -> str | None:
    """Return one clean, validated URL from a Telegram message."""
    match = URL_RE.search(text)
    if not match:
        return None
    candidate = match.group(0).rstrip(".,!?)]}")
    if len(candidate) > MAX_URL_LENGTH:
        return None
    parsed = urlparse(candidate)
    try:
        host = parsed.hostname.lower().rstrip(".") if parsed.hostname else ""
    except ValueError:
        return None
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or not host:
        return None
    try:
        host_ip = ipaddress.ip_address(host)
    except ValueError:
        host_ip = None
    if host in {"localhost", "localhost.localdomain"} or (host_ip and (host_ip.is_private or host_ip.is_loopback or host_ip.is_link_local)):
        return None
    if any_https or host in SUPPORTED_CHAT_HOSTS:
        return candidate
    return None


def validate_remote_url(url: str) -> None:
    """Reject URLs resolving to private, local, or otherwise non-public IPs."""
    parsed = urlparse(url)
    host = parsed.hostname
    if parsed.scheme != "https" or not host:
        raise ValueError("Only HTTPS URLs are allowed")
    try:
        addresses = {
            ipaddress.ip_address(result[4][0])
            for result in socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)
        }
    except (OSError, ValueError):
        raise ValueError("The source host could not be resolved safely") from None
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError("The source host resolves to a non-public network")


def safe_log_url(url: str) -> str:
    """Log only the origin/path, never query parameters or fragments."""
    parsed = urlsplit(url)
    path = parsed.path[:160]
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def safe_log_error(exc: Exception) -> str:
    """Redact signed URLs and bound exception text before logging."""
    return re.sub(r"https?://[^\s]+", "[url-redacted]", str(exc))[:500]


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
    STATES[key] = LinkState(
        url=url,
        chat_id=update.effective_chat.id,
        user_id=user.id if user else 0,
        created_at=time.monotonic(),
        title=(info or {}).get("title", "Video"),
        duration=(info or {}).get("duration"),
    )
    prune_states()
    return key


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


def format_duration(seconds: int | float | None) -> str:
    if not seconds:
        return "unknown"
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


def safe_filename(title: str, extension: str) -> str:
    cleaned = re.sub(r"[^\w\-. ]+", "", title, flags=re.UNICODE).strip(" .") or "download"
    return f"{cleaned[:80]}.{extension}"


def r2_is_configured() -> bool:
    values = (R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME)
    return all(value and not value.startswith("your-") for value in values)


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
    if R2_PUBLIC_BASE_URL:
        return f"{R2_PUBLIC_BASE_URL.rstrip('/')}/{object_key}"
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


def display_error(exc: Exception) -> str:
    text = str(exc).lower()
    if "private" in text or "login" in text:
        return "This video is private or requires an account, so it cannot be downloaded."
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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "Send a YouTube, TikTok, or Instagram link, or use /download <https-url>.\n\n"
        "Choose a quality, then I’ll download it and send it back."
    )


async def make_choice(update: Update, url: str, info: dict[str, Any] | None = None) -> None:
    key = save_state(update, url, info)
    title = (info or {}).get("title", "Video")
    keyboard = [
        [InlineKeyboardButton("360p · fast", callback_data=f"d|360p|{key}"), InlineKeyboardButton("480p", callback_data=f"d|480p|{key}")],
        [InlineKeyboardButton("720p", callback_data=f"d|720p|{key}"), InlineKeyboardButton("1080p", callback_data=f"d|1080p|{key}")],
        [InlineKeyboardButton("Best quality", callback_data=f"d|best|{key}")],
        [InlineKeyboardButton("MP3 · 128 kbps", callback_data=f"d|mp3_128|{key}"), InlineKeyboardButton("MP3 · 192 kbps", callback_data=f"d|mp3_192|{key}")],
        [InlineKeyboardButton("MP3 · 320 kbps", callback_data=f"d|mp3_320|{key}")],
    ]
    await update.effective_message.reply_text(
        f"🎬 {title}\n⏱ Duration: {format_duration((info or {}).get('duration'))}\n\nChoose a format:",
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
        await update.effective_message.reply_text("Please send a YouTube, TikTok, or Instagram HTTPS link.")
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
) -> None:
    title = info.get("title", "Downloaded file")
    size_text = f"{size_bytes / 1024 / 1024:.1f} MB" if size_bytes else "large"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬇️ Download file", url=url)]])
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"✅ Ready: {title[:700]}\nFormat: {fmt}\nSize: {size_text}\n\n"
            "The media exceeds Telegram's upload limit, so I’m giving you a "
            "temporary download link instead."
        ),
        reply_markup=keyboard,
    )


def progress_text(progress: dict[str, Any], fmt: str) -> str:
    """Turn a yt-dlp progress hook payload into a short Telegram status."""
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
        bar = "█" * filled + "░" * (10 - filled)
        details = f"{percent:5.1f}%  {bar}"
    else:
        details = f"{downloaded / 1024 / 1024:.1f} MB"
    if speed:
        details += f"  {speed / 1024 / 1024:.1f} MB/s"
    if eta is not None:
        details += f"  ETA {int(eta) // 60}:{int(eta) % 60:02d}"
    return f"⬇️ Downloading {fmt}\n{details}"


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
        await query.edit_message_text(f"⬇️ Downloading {fmt}…")
        await context.bot.send_chat_action(chat_id=state.chat_id, action=ChatAction.UPLOAD_DOCUMENT)
        try:
            with tempfile.TemporaryDirectory(prefix="ytbot-") as tmpdir:
                loop = asyncio.get_running_loop()
                info, filename, extension = await run_download_with_progress(loop, state.url, fmt, tmpdir, query)
                file_size = filename.stat().st_size
                if DELIVERY_MODE == "r2":
                    await query.edit_message_text("☁️ Uploading to cloud storage…\nDownload: 100%")
                    download_url = await loop.run_in_executor(EXECUTOR, upload_to_r2, filename, info, extension)
                    await send_r2_link(context, state.chat_id, download_url, info, fmt, file_size)
                elif DELIVERY_MODE == "auto" and file_size > MAX_UPLOAD_BYTES and r2_is_configured():
                    await query.edit_message_text("☁️ Uploading to cloud storage…\nDownload: 100%")
                    download_url = await loop.run_in_executor(EXECUTOR, upload_to_r2, filename, info, extension)
                    await send_r2_link(context, state.chat_id, download_url, info, fmt, file_size)
                elif file_size <= MAX_UPLOAD_BYTES:
                    await query.edit_message_text("⬆️ Uploading to Telegram…\nDownload: 100%")
                    await send_file(context, state.chat_id, filename, info, extension, fmt)
                else:
                    raise ValueError("The file exceeds Telegram's upload limit and cloud delivery is not configured")
                await query.delete_message()
        except (TelegramError, BadRequest):
            LOG.exception("Telegram upload failed for chat %s", state.chat_id)
            await query.edit_message_text("Telegram could not accept the file. Try a lower quality.")
        except Exception as exc:
            LOG.info("download failed for %s: %s", safe_log_url(state.url), safe_log_error(exc))
            await query.edit_message_text(f"❌ {display_error(exc)}")
        finally:
            STATES.pop(key, None)


async def post_init(application: Application) -> None:
    LOG.info("Bot started with %s download worker(s)", MAX_WORKERS)


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN must be set")
    builder = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init)
    if TELEGRAM_API_BASE_URL:
        builder = builder.base_url(TELEGRAM_API_BASE_URL)
    if TELEGRAM_API_FILE_BASE_URL:
        builder = builder.base_file_url(TELEGRAM_API_FILE_BASE_URL)
    application = builder.build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("download", download_command))
    application.add_handler(CallbackQueryHandler(button_handler, pattern=r"^d\|"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
