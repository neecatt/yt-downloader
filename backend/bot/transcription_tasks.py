"""Celery worker task for serialized, cost-controlled transcription."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from telegram import Bot

from .queue.config import app
from .persistence import activity_store
from .i18n import tr
from .platforms.media import display_error
from .integrations.transcription import format_transcript, transcript_filename, transcribe_audio_url_sync


LOG = logging.getLogger("downloader_bot.transcription_worker")
MAX_RETRIES = max(0, int(os.getenv("TRANSCRIPTION_MAX_RETRIES", "2")))
_WORKER_INITIALIZED = False
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


def initialize_worker_state() -> None:
    global _WORKER_INITIALIZED
    if _WORKER_INITIALIZED:
        return
    activity_store.initialize()
    recovered = activity_store.recover_stale_transcription_jobs(
        stale_after_seconds=max(3600, int(os.getenv("TRANSCRIPTION_STALE_JOB_SECONDS", "21600")))
    )
    if recovered:
        LOG.warning("event=transcription_stale_jobs_recovered count=%s", recovered)
    _WORKER_INITIALIZED = True


def _retryable(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in ("timeout", "timed out", "connection", "temporarily", "429", "500", "502", "503", "resource exhausted", "rate limit"))


async def _edit_status(job: dict[str, Any], text: str) -> None:
    message_id = job.get("status_message_id")
    if not message_id:
        return
    try:
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            raise RuntimeError("Telegram bot token is not configured")
        async with Bot(token=token) as bot:
            await bot.edit_message_text(chat_id=job["chat_id"], message_id=message_id, text=text)
    except Exception:
        LOG.warning("event=transcription_status_update_failed job_id=%s", job["id"], exc_info=True)


async def _deliver(job: dict[str, Any], transcript: str, title: str, language: str) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Telegram bot token is not configured")
    filename = transcript_filename(title)
    directory = Path(tempfile.mkdtemp(prefix="transcript-artifact-"))
    artifact = directory / filename
    artifact.write_text(transcript, encoding="utf-8")
    try:
        async with Bot(token=token) as bot:
            if job.get("status_message_id"):
                try:
                    await bot.delete_message(chat_id=job["chat_id"], message_id=job["status_message_id"])
                except Exception:
                    LOG.debug("event=transcription_status_delete_skipped job_id=%s", job["id"], exc_info=True)
            with artifact.open("rb") as document:
                await bot.send_document(
                    chat_id=job["chat_id"],
                    document=document,
                    filename=filename,
                    caption=tr(language, "transcription_ready", detected_language=language),
                    read_timeout=120,
                    write_timeout=120,
                )
    finally:
        shutil.rmtree(directory, ignore_errors=True)


@app.task(bind=True, name="transcription.process", max_retries=MAX_RETRIES, track_started=True)
def process_transcription(self: Any, job_id: str) -> dict[str, Any]:
    """Process one durable job and acknowledge it only after completion."""
    initialize_worker_state()
    job = activity_store.get_transcription_job(job_id)
    if not job:
        LOG.error("event=transcription_job_missing job_id=%s", job_id)
        return {"status": "missing", "job_id": job_id}
    if job["status"] in {"completed", "cancelled"}:
        return {"status": job["status"], "job_id": job_id}

    started = time.perf_counter()
    directory = Path(tempfile.mkdtemp(prefix="transcription-"))
    object_key: str | None = None
    activity_store.update_transcription_job(job_id, status="processing", increment_attempts=True)
    try:
        try:
            from main import download_sync, upload_to_r2_with_key, delete_r2_object
        except ImportError:
            from ..main import download_sync, upload_to_r2_with_key, delete_r2_object

        language = job["language"]
        activity_store.update_event(job.get("activity_id"), status="started", action="transcribe")
        LOG.info("event=transcription_job_started job_id=%s", job_id)
        asyncio.run(_edit_status(job, tr(language, "downloading", fmt="mp3")))
        info, audio_file, _ = download_sync(job["source_url"], "mp3", str(directory))
        activity_store.update_event(job.get("activity_id"), status="started", title=info.get("title"), duration_ms=int(float(info.get("duration") or 0) * 1000) if info.get("duration") else None)
        audio_url, object_key = upload_to_r2_with_key(audio_file, info, "mp3")
        asyncio.run(_edit_status(job, tr(language, "transcription_processing")))
        result = transcribe_audio_url_sync(audio_url, str(info.get("title") or "Transcript"), info.get("duration"))
        transcript = format_transcript(result)
        asyncio.run(_deliver(job, transcript, str(result.get("title") or "Transcript"), language))
        activity_store.update_transcription_job(job_id, status="completed")
        activity_store.update_event(job.get("activity_id"), status="completed", action="transcribe", title=result.get("title"), duration_ms=int(float(result.get("duration") or 0) * 1000) if result.get("duration") else None)
        LOG.info("event=transcription_job_finished job_id=%s total_duration_seconds=%.2f", job_id, time.perf_counter() - started)
        return {"status": "completed", "job_id": job_id}
    except Exception as exc:
        if _retryable(exc) and self.request.retries < MAX_RETRIES:
            activity_store.update_transcription_job(job_id, status="queued", error=str(exc))
            LOG.warning("event=transcription_job_retry job_id=%s retry=%s error=%s", job_id, self.request.retries + 1, display_error(exc))
            raise self.retry(exc=exc, countdown=min(300, 2 ** self.request.retries * 10))
        activity_store.update_transcription_job(job_id, status="failed", error=str(exc))
        activity_store.update_event(job.get("activity_id"), status="failed", action="transcribe", error=display_error(exc, job["language"]))
        try:
            asyncio.run(_edit_status(job, display_error(exc, job["language"])))
        except Exception:
            LOG.warning("event=transcription_failure_notification_failed job_id=%s", job_id, exc_info=True)
        LOG.exception("event=transcription_job_failed job_id=%s total_duration_seconds=%.2f", job_id, time.perf_counter() - started)
        raise
    finally:
        if object_key:
            try:
                from main import delete_r2_object
                delete_r2_object(object_key)
            except Exception:
                LOG.warning("event=transcription_cleanup_failed job_id=%s", job_id, exc_info=True)
        shutil.rmtree(directory, ignore_errors=True)
