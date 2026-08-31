"""Telegram command handlers.

The application module owns configuration and service wiring.  Commands use
that assembled application as a dependency so this module contains only the
Telegram interaction layer.
"""

from __future__ import annotations

import asyncio
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes


def _app() -> Any:
    import __main__
    if hasattr(__main__, "BOT_TOKEN"):
        return __main__
    from backend import main
    return main


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    app = _app()
    app._record_contact(update)
    language = app.language_for_update(update)
    await update.effective_message.reply_text(
        f"{app.tr(language, 'welcome')}\n\n{app.tr(language, 'help_hint')}\n{app.tr(language, 'settings_hint')}",
        reply_markup=app.start_keyboard(language),
    )


async def support(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    app = _app()
    app._record_contact(update)
    language = app.language_for_update(update)
    if not app.support_is_configured():
        await update.effective_message.reply_text(app.tr(language, "support_unconfigured"))
        return
    await app.send_support_prompt(context, update.effective_chat.id, update.effective_user.id, force=True, language=language)


async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    app = _app()
    app._record_contact(update)
    language = app.language_for_update(update)
    await update.effective_message.reply_text(app.tr(language, "settings_language"), reply_markup=app.language_keyboard())


async def language_button(update: Update, context: ContextTypes.DEFAULT_TYPE, language: str) -> None:
    app = _app()
    selected = app.update_chat_language(update.effective_chat.id, language)
    await update.callback_query.edit_message_text(
        f"{app.tr(selected, 'welcome')}\n\n{app.tr(selected, 'help_hint')}\n{app.tr(selected, 'settings_hint')}",
        reply_markup=app.start_keyboard(selected),
    )


async def feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    app = _app()
    app._record_contact(update)
    language = app.language_for_update(update)
    text = " ".join(context.args).strip()
    if not text:
        await update.effective_message.reply_text(app.tr(language, "feedback_usage"))
        return
    if len(text) > 4096:
        await update.effective_message.reply_text(app.tr(language, "feedback_too_long"))
        return
    try:
        try:
            from ..persistence import activity_store as store
        except ImportError:
            from bot.persistence import activity_store as store
        user, chat = update.effective_user, update.effective_chat
        feedback_id = store.create_feedback(
            chat_id=chat.id,
            username=f"@{user.username}" if getattr(user, "username", None) else None,
            display_name=getattr(user, "full_name", None) if user else None,
            feedback=text,
        )
    except Exception:
        feedback_id = None
        app.LOG.warning("Could not save user feedback", exc_info=True)
    await update.effective_message.reply_text(app.tr(language, "feedback_saved" if feedback_id else "feedback_failed"))


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    app = _app()
    app._record_contact(update)
    language = app.language_for_update(update)
    await update.effective_message.reply_text(f"{app.tr(language, 'help')}\n\n{app.tr(language, 'transcription_help')}")


async def make_choice(update: Update, url: str, info: dict[str, Any] | None = None) -> None:
    app = _app()
    key = app.save_state(update, url, info)
    language = app.language_for_update(update)
    title = (info or {}).get("title", "Video")
    duration = (info or {}).get("duration")
    duration_line = f"\n⏱ {app.tr(language, 'duration')}: {app.format_duration(duration)}" if duration else ""
    keyboard = [
        [app.InlineKeyboardButton(app.tr(language, "fast_360"), callback_data=f"d|360p|{key}"), app.InlineKeyboardButton(app.tr(language, "quality_480"), callback_data=f"d|480p|{key}")],
        [app.InlineKeyboardButton(app.tr(language, "quality_720"), callback_data=f"d|720p|{key}"), app.InlineKeyboardButton(app.tr(language, "quality_1080"), callback_data=f"d|1080p|{key}")],
        [app.InlineKeyboardButton(app.tr(language, "best"), callback_data=f"d|best|{key}")],
        [app.InlineKeyboardButton(app.tr(language, "mp3_128"), callback_data=f"d|mp3_128|{key}"), app.InlineKeyboardButton(app.tr(language, "mp3_192"), callback_data=f"d|mp3_192|{key}")],
        [app.InlineKeyboardButton(app.tr(language, "mp3_320"), callback_data=f"d|mp3_320|{key}")],
        [app.InlineKeyboardButton(app.tr(language, "transcribe"), callback_data=f"t|{key}"), app.InlineKeyboardButton(app.tr(language, "summarize"), callback_data=f"s|{key}")],
    ]
    await update.effective_message.reply_text(app.tr(language, "choose_format", title=title, duration=duration_line), reply_markup=app.InlineKeyboardMarkup(keyboard))


async def download(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    app = _app()
    app._record_contact(update)
    language = app.language_for_update(update)
    if not context.args:
        await update.effective_message.reply_text(app.tr(language, "download_usage"))
        return
    url = app.extract_url(context.args[0], any_https=app.ALLOW_GENERIC_HTTPS)
    if not url:
        await update.effective_message.reply_text(app.tr(language, "download_url"))
        return
    user_id = update.effective_user.id if update.effective_user else 0
    if not app.allow_analysis(user_id):
        await update.effective_message.reply_text(app.tr(language, "analysis_limit"))
        return
    status = await update.effective_message.reply_text(app.tr(language, "analyzing"))
    try:
        info = await asyncio.get_running_loop().run_in_executor(app.EXECUTOR, app.analyze_url, url)
        await status.delete()
        await app.make_choice(update, url, info)
    except Exception as exc:
        app.LOG.info("analysis failed for %s: %s", app.safe_log_url(url), app.safe_log_error(exc))
        if app.should_offer_transcription_fallback(exc) and app.transcription_is_configured() and app.r2_is_configured():
            key = app.save_state(update, url)
            await status.edit_text(f"{app.display_error(exc, language)}\n\n{app.tr(language, 'transcription_fallback')}", reply_markup=app.transcription_fallback_keyboard(key, language))
        else:
            await status.edit_text(app.display_error(exc, language))


async def _run_transcription_command(update: Update, context: ContextTypes.DEFAULT_TYPE, job_type: str) -> None:
    app = _app()
    app._record_contact(update)
    language = app.language_for_update(update)
    if not context.args:
        await update.effective_message.reply_text(app.tr(language, "summarize_usage" if job_type == "summary" else "transcribe_usage"))
        return
    url = app.extract_url(context.args[0], any_https=app.ALLOW_GENERIC_HTTPS)
    if not url:
        await update.effective_message.reply_text(app.tr(language, "summarize_url" if job_type == "summary" else "transcribe_url"))
        return
    if not app.transcription_is_configured():
        await update.effective_message.reply_text(app.tr(language, "transcription_unavailable"))
        return
    if not app.r2_is_configured():
        await update.effective_message.reply_text(app.tr(language, "transcription_storage"))
        return
    if not app.queue_is_configured():
        await update.effective_message.reply_text(app.tr(language, "transcription_queue_unavailable"))
        return
    user_id = update.effective_user.id if update.effective_user else 0
    if not app.allow_analysis(user_id):
        await update.effective_message.reply_text(app.tr(language, "analysis_limit"))
        return
    status_key = "summarization_starting" if job_type == "summary" else "transcription_starting"
    status = await update.effective_message.reply_text(app.tr(language, status_key))
    activity_id = app._create_activity_event(update, url, None, action=job_type)
    await app._run_transcription(update, status, url, language, activity_id=activity_id, job_type=job_type)


async def transcribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _run_transcription_command(update, context, "transcript")


async def summarize(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _run_transcription_command(update, context, "summary")
