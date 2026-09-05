"""Free-form Telegram message handling and transcription enqueueing."""

from __future__ import annotations

from typing import Any
import asyncio
from datetime import datetime, timedelta, timezone

from .commands import _app


async def run_transcription(update: Any, status: Any, url: str, language: str, *, activity_id: str | None = None, job_type: str = "transcript") -> None:
    app = _app()

    async def edit(text: str, **kwargs: Any) -> None:
        method = getattr(status, "edit_message_text", None) or getattr(status, "edit_text")
        await method(text, **kwargs)

    if not app.queue_is_configured():
        await edit(app.tr(language, "transcription_queue_unavailable"))
        return
    from ..persistence import activity_store
    user = update.effective_user
    job_id: str | None = None
    try:
        job_id = activity_store.create_transcription_job(
            activity_id=activity_id, chat_id=update.effective_chat.id,
            user_id=user.id if user else 0, source_url=url, language=language,
            status_message_id=getattr(status, "message_id", None),
            job_type=job_type,
        )
        if not job_id:
            raise RuntimeError("Could not create transcription job")
        app.enqueue_transcription(job_id)
    except Exception as exc:
        app.LOG.warning("event=transcription_enqueue_failed error=%s", app.safe_log_error(exc), exc_info=True)
        if job_id:
            # The database row is the source of truth. A temporary Redis/Celery
            # publish failure must leave it queued for the recovery loop.
            activity_store.update_transcription_job(
                job_id,
                status="queued",
                error=str(exc),
                next_attempt_at=datetime.now(timezone.utc) + timedelta(seconds=60),
            )
            app._update_activity(activity_id, status="started", action=job_type)
            await edit(app.tr(language, "transcription_saved_for_retry"))
        else:
            app._update_activity(activity_id, status="failed", action=job_type, error=app.display_error(exc, language))
            await edit(app.tr(language, "transcription_queue_unavailable"))
        return

    # Telegram edits are deliberately outside the enqueue failure boundary:
    # Celery may start the job and update this message concurrently.
    try:
        queue_status = activity_store.get_transcription_queue_status(job_id)
        if queue_status and queue_status.get("position"):
            await edit(app.tr(
                language, "transcription_queued_with_position",
                position=queue_status["position"], eta_minutes=queue_status["eta_minutes"],
            ))
        else:
            await edit(app.tr(language, "transcription_queued"))
        app.LOG.info("event=transcription_enqueued job_id=%s chat_id=%s", job_id, update.effective_chat.id)
    except Exception:
        app.LOG.warning("event=transcription_queue_status_update_failed job_id=%s", job_id, exc_info=True)


async def handle(update: Any, context: Any) -> None:
    app = _app()
    app._record_contact(update)
    language = app.language_for_update(update)
    text = update.effective_message.text or ""
    app._record_chat_message(update, text)
    url = app.extract_url(text)
    if not url:
        await update.effective_message.reply_text(app.tr(language, "invalid_link"))
        return
    if app.is_x_photo_link(url):
        await update.effective_message.reply_text(app.tr(language, "video_only"))
        return
    if not app.should_analyze_media_type(url):
        await app.make_choice(update, url)
        return
    user_id = update.effective_user.id if update.effective_user else 0
    if not app.allow_analysis(user_id):
        await update.effective_message.reply_text(app.tr(language, "analysis_limit"))
        return
    status = await update.effective_message.reply_text(app.tr(language, "checking"))
    try:
        info = await asyncio.get_running_loop().run_in_executor(app.EXECUTOR, app.analyze_url, url)
        await status.delete()
        await app.make_choice(update, url, info)
    except Exception as exc:
        app.LOG.info("media-type analysis failed for %s: %s", app.safe_log_url(url), app.safe_log_error(exc))
        if app.should_offer_transcription_fallback(exc) and app.transcription_is_configured() and app.r2_is_configured():
            key = app.save_state(update, url)
            await status.edit_text(f"{app.display_error(exc, language)}\n\n{app.tr(language, 'transcription_fallback')}", reply_markup=app.transcription_fallback_keyboard(key, language))
        else:
            await status.edit_text(app.display_error(exc, language))
