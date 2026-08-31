"""Telegram callback workflows for language, transcription, and delivery."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from telegram.error import BadRequest, TelegramError

from .commands import _app


async def pending_delivery(update: Any, context: Any, mode: str, key: str) -> None:
    app = _app()
    query = update.callback_query
    language = app.language_for_update(update)
    if mode == "r2" and not app.r2_is_configured():
        await query.edit_message_text(app.tr(language, "link_unconfigured"))
        return
    pending = app.take_pending_delivery(key, update)
    if not pending:
        await query.edit_message_text(app.tr(language, "delivery_expired"))
        return
    lock = app.DOWNLOAD_LOCKS.setdefault(pending.chat_id, asyncio.Lock())
    started = time.perf_counter()
    app.LOG.info("event=delivery_job_started chat_id=%s mode=%s", pending.chat_id, mode)
    try:
        async with lock:
            loop = asyncio.get_running_loop()
            if mode == "telegram":
                await query.edit_message_text(app.tr(language, "upload_telegram"))
                await app.send_file(context, pending.chat_id, pending.filename, pending.info, pending.extension, pending.fmt)
                await app.send_support_prompt(context, pending.chat_id, pending.user_id)
                delivery = "telegram"
            else:
                await query.edit_message_text(app.tr(language, "prepare_link"))
                url = await loop.run_in_executor(app.EXECUTOR, app.upload_to_r2, pending.filename, pending.info, pending.extension)
                offer_support = app.support_prompt_allowed(pending.chat_id, pending.user_id)
                await app.send_r2_link(context, pending.chat_id, url, pending.info, pending.fmt, pending.size_bytes, app.support_keyboard(language) if offer_support else None, selected_by_user=True)
                if offer_support:
                    app.mark_support_prompt_shown(pending.chat_id, pending.user_id)
                delivery = "r2"
            app._update_activity(pending.activity_id, status="completed", fmt=pending.fmt, delivery=delivery, size_bytes=pending.size_bytes, duration_ms=int(pending.info.get("duration", 0) * 1000) if pending.info.get("duration") else None, title=pending.info.get("title"))
            await query.delete_message()
    except (TelegramError, BadRequest):
        app.LOG.exception("Pending delivery failed for chat %s", pending.chat_id)
        app._update_activity(pending.activity_id, status="failed", error="Telegram could not accept the file")
        await query.edit_message_text(app.tr(language, "telegram_failed_other"))
    except Exception as exc:
        app.LOG.info("pending delivery failed: %s", app.safe_log_error(exc))
        app._update_activity(pending.activity_id, status="failed", error=app.display_error(exc, language))
        await query.edit_message_text(f"❌ {app.display_error(exc, language)}")
    finally:
        app.discard_pending_delivery(pending)
        app.log_timing(app.LOG, "delivery_job_finished", started, chat_id=pending.chat_id, mode=mode)


async def handle(update: Any, context: Any) -> None:
    app = _app()
    query = update.callback_query
    await query.answer()
    data = query.data if isinstance(query.data, str) else ""
    if data.startswith("lang|"):
        await app.language_button_handler(update, context, data.split("|", 1)[1])
        return
    if data.startswith(("t|", "s|")):
        job_type = "summary" if data.startswith("s|") else "transcript"
        key = data.split("|", 1)[1]
        language = app.language_for_update(update)
        state = app.get_state(key, update)
        if not state:
            await query.edit_message_text(app.tr(language, "link_expired"))
            return
        if not app.transcription_is_configured():
            await query.edit_message_text(app.tr(language, "transcription_unavailable"))
            return
        if not app.r2_is_configured():
            await query.edit_message_text(app.tr(language, "transcription_storage"))
            return
        if not app.queue_is_configured():
            await query.edit_message_text(app.tr(language, "transcription_queue_unavailable"))
            return
        if not app.allow_analysis(state.user_id):
            await query.edit_message_text(app.tr(language, "analysis_limit"))
            return
        app._update_activity(state.activity_id, status="started", action=job_type)
        await app._run_transcription(update, query, state.url, language, activity_id=state.activity_id, job_type=job_type)
        app.STATES.pop(key, None)
        return
    try:
        action, value, key = data.split("|", 2)
    except ValueError:
        await query.edit_message_text(app.tr(app.language_for_update(update), "invalid_button"))
        return
    if action == "p":
        await pending_delivery(update, context, value, key)
        return
    if action != "d":
        await query.edit_message_text(app.tr(app.language_for_update(update), "invalid_button"))
        return
    state = app.get_state(key, update)
    language = app.language_for_update(update)
    if not state:
        await query.edit_message_text(app.tr(language, "link_expired"))
        return
    lock = app.DOWNLOAD_LOCKS.setdefault(state.chat_id, asyncio.Lock())
    if lock.locked():
        await query.edit_message_text(app.tr(language, "already_running"))
        return
    started = time.perf_counter()
    app.LOG.info("event=download_job_started chat_id=%s source=%s format=%s", state.chat_id, app.safe_log_url(state.url), value)
    async with lock:
        if not app.allow_download(state.user_id):
            await query.edit_message_text(app.tr(language, "download_limit"))
            return
        await query.edit_message_text(app.tr(language, "downloading", fmt=value))
        await context.bot.send_chat_action(chat_id=state.chat_id, action=app.ChatAction.UPLOAD_DOCUMENT)
        directory = Path(tempfile.mkdtemp(prefix="ytbot-"))
        keep_pending = False
        try:
            info, filename, extension = await app.run_download_with_progress(asyncio.get_running_loop(), state.url, value, str(directory), query, language)
            size = filename.stat().st_size
            if app.DELIVERY_MODE == "r2" or (app.DELIVERY_MODE == "auto" and size > app.MAX_UPLOAD_BYTES and app.r2_is_configured()):
                await query.edit_message_text(app.tr(language, "upload_cloud"))
                url = await asyncio.get_running_loop().run_in_executor(app.EXECUTOR, app.upload_to_r2, filename, info, extension)
                offer_support = app.support_prompt_allowed(state.chat_id, state.user_id)
                await app.send_r2_link(context, state.chat_id, url, info, value, size, app.support_keyboard(language) if offer_support else None)
                if offer_support:
                    app.mark_support_prompt_shown(state.chat_id, state.user_id)
                delivery = "r2"
            elif app.DELIVERY_MODE == "auto" and size <= app.MAX_UPLOAD_BYTES and app.r2_is_configured():
                pending_key = app.save_pending_delivery(filename=filename, directory=directory, update=update, info=info, extension=extension, fmt=value, size_bytes=size, activity_id=state.activity_id)
                keep_pending = True
                await query.edit_message_text(app.tr(language, "ready_choice", title=info.get("title", "Downloaded file")[:700], size=size / 1024 / 1024), reply_markup=app.delivery_choice_keyboard(pending_key, language))
                return
            elif size <= app.MAX_UPLOAD_BYTES:
                await query.edit_message_text(app.tr(language, "upload_telegram"))
                await app.send_file(context, state.chat_id, filename, info, extension, value)
                await app.send_support_prompt(context, state.chat_id, state.user_id)
                delivery = "telegram"
            else:
                raise ValueError("The file exceeds Telegram's upload limit and cloud delivery is not configured")
            app._update_activity(state.activity_id, status="completed", fmt=value, delivery=delivery, size_bytes=size, duration_ms=int(info.get("duration", 0) * 1000) if info.get("duration") else None, title=info.get("title"))
            await query.delete_message()
        except (TelegramError, BadRequest):
            app.LOG.exception("Telegram upload failed for chat %s", state.chat_id)
            app._update_activity(state.activity_id, status="failed", error="Telegram could not accept the file")
            await query.edit_message_text(app.tr(language, "telegram_failed_quality"))
        except Exception as exc:
            app.LOG.info("download failed for %s: %s", app.safe_log_url(state.url), app.safe_log_error(exc))
            app._update_activity(state.activity_id, status="failed", error=app.display_error(exc, language))
            await query.edit_message_text(f"❌ {app.display_error(exc, language)}")
        finally:
            if not keep_pending:
                shutil.rmtree(directory, ignore_errors=True)
            app.STATES.pop(key, None)
            app.log_timing(app.LOG, "download_job_finished", started, chat_id=state.chat_id, format=value, source=app.safe_log_url(state.url))
