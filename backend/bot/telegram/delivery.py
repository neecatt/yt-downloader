"""Telegram media delivery operations.

This module owns file uploads and delivery-link presentation.  The application
module supplies runtime configuration and orchestration dependencies through
the already assembled application module.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError

from .commands import _app


async def send_file(context: Any, chat_id: int, filename: Path, info: dict[str, Any], extension: str, fmt: str) -> None:
    app = _app()
    started = time.perf_counter()
    size = filename.stat().st_size
    if size > app.MAX_UPLOAD_BYTES:
        raise ValueError("The file is too large for the configured Telegram upload limit")
    title = info.get("title", "Downloaded video")
    name = app.safe_filename(title, extension)
    caption = f"{title[:900]} · {fmt}"
    with filename.open("rb") as media:
        if extension == "mp3":
            await context.bot.send_audio(chat_id=chat_id, audio=media, filename=name, title=title[:64], caption=caption)
        elif extension == "mp4":
            await context.bot.send_video(chat_id=chat_id, video=media, filename=name, supports_streaming=True, caption=caption, read_timeout=300, write_timeout=300)
        else:
            await context.bot.send_document(chat_id=chat_id, document=media, filename=name, caption=caption, read_timeout=300, write_timeout=300)
    app.log_timing(app.LOG, "telegram_delivery_finished", started, chat_id=chat_id, size_bytes=size, extension=extension)


async def send_r2_link(context: Any, chat_id: int, url: str, info: dict[str, Any], fmt: str, size_bytes: int | None = None, reply_markup: InlineKeyboardMarkup | None = None, selected_by_user: bool = False) -> None:
    app = _app()
    language = app.chat_language(chat_id)
    title = info.get("title", "Downloaded file")
    size_text = f"{size_bytes / 1024 / 1024:.1f} MB" if size_bytes else "large"
    rows = [[InlineKeyboardButton(app.tr(language, "download_file"), url=url)]]
    if reply_markup:
        rows.extend(reply_markup.inline_keyboard)
    await context.bot.send_message(
        chat_id=chat_id,
        text=(f"✅ Ready: {title[:700]}\n{app.tr(language, 'format_label')}: {fmt}\n{app.tr(language, 'size_label')}: {size_text}\n\n" + app.tr(language, "ready_link_choice" if selected_by_user else "ready_link_large")),
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def download_with_progress(loop: Any, url: str, fmt: str, tmpdir: str, query: Any, language: str = "en") -> tuple[dict[str, Any], Path, str]:
    """Run the blocking downloader while throttling Telegram progress edits."""
    app = _app()
    progress_queue: Any = __import__("asyncio").Queue()

    def on_progress(payload: dict[str, Any]) -> None:
        loop.call_soon_threadsafe(progress_queue.put_nowait, payload)

    download_task = loop.run_in_executor(app.EXECUTOR, app.download_sync, url, fmt, tmpdir, on_progress)
    last_update = 0.0
    latest: dict[str, Any] | None = None
    while not download_task.done():
        try:
            latest = await __import__("asyncio").wait_for(progress_queue.get(), timeout=0.5)
        except __import__("asyncio").TimeoutError:
            continue
        now = time.monotonic()
        if now - last_update >= 1.5 or latest.get("status") in {"finished", "started", "processing"}:
            try:
                await query.edit_message_text(app.progress_text(latest, fmt, language))
                last_update = now
            except TelegramError:
                app.LOG.debug("Unable to update download progress", exc_info=True)
    result = await download_task
    while not progress_queue.empty():
        latest = progress_queue.get_nowait()
    if latest and latest.get("status") == "finished":
        try:
            await query.edit_message_text(app.progress_text(latest, fmt, language))
        except TelegramError:
            app.LOG.debug("Unable to update final download progress", exc_info=True)
    return result
