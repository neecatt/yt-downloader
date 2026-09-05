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
from datetime import datetime, timedelta, timezone

from telegram import Bot

from ..queue.config import app
from ..queue.recovery import retryable, retry_delay_seconds
from ..persistence import activity_store
from ..i18n import tr
from ..platforms.media import display_error
from ..integrations.transcription import format_transcript, transcript_filename, transcribe_audio_url_sync
from ..integrations.cookies import prepare_cookie_file
from ..integrations.r2_cleanup import schedule_object_delete
from ..services.downloader import DownloaderConfig, download
from ..services import storage


LOG = logging.getLogger("downloader_bot.transcription_worker")
MAX_RETRIES = max(0, int(os.getenv("TRANSCRIPTION_MAX_RETRIES", "2")))
try:
    RETRY_AFTER_MAX_SECONDS = max(60, int(os.getenv("TRANSCRIPTION_RETRY_AFTER_MAX_SECONDS", "900")))
except ValueError:
    RETRY_AFTER_MAX_SECONDS = 900
_WORKER_INITIALIZED = False
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _worker_downloader_config() -> DownloaderConfig:
    return DownloaderConfig(
        max_bytes=_int("MAX_DOWNLOAD_MB", 2048) * 1024 * 1024,
        fragment_workers=max(1, _int("FRAGMENT_WORKERS", 4)),
        http_chunk_size_mb=max(1, _int("HTTP_CHUNK_SIZE_MB", 10)),
        cookies_file=prepare_cookie_file(os.getenv("YTDLP_COOKIES_B64"), os.getenv("YTDLP_COOKIES_FILE")),
        proxy=os.getenv("YTDLP_PROXY") or None,
        js_runtime=os.getenv("YTDLP_JS_RUNTIME") or None,
        player_client=os.getenv("YTDLP_PLAYER_CLIENT") or None,
        po_token=os.getenv("YTDLP_PO_TOKEN") or None,
        po_provider_url=os.getenv("YTDLP_POT_PROVIDER_URL") or None,
    )


def _storage_config() -> tuple[str | None, str | None, str | None, str | None, int, int]:
    endpoint = os.getenv("R2_ENDPOINT_URL") or None
    access = os.getenv("R2_ACCESS_KEY_ID") or None
    secret = os.getenv("R2_SECRET_ACCESS_KEY") or None
    api_token = os.getenv("R2_API_TOKEN") or ""
    if api_token and ":" in api_token:
        access, secret = api_token.split(":", 1)
    return endpoint, access, secret, os.getenv("R2_BUCKET_NAME") or None, _int("R2_PRESIGNED_URL_TTL_SECONDS", 86400), max(1, _int("R2_UPLOAD_CONCURRENCY", 8))


def _r2_client():
    endpoint, access, secret, bucket, _, _ = _storage_config()
    return storage.client(endpoint, access, secret, bucket)


def _download_sync(url: str, fmt: str, directory: str):
    return download(_worker_downloader_config(), url, fmt, directory)


def _upload_to_r2(filename: Path, info: dict[str, Any], extension: str) -> tuple[str, str]:
    endpoint, access, secret, bucket, ttl, concurrency = _storage_config()
    return storage.upload(
        filename, info, extension, client_factory=_r2_client, bucket=bucket or "",
        public_base_url=None, url_ttl=ttl, retention_seconds=ttl,
        schedule_delete=schedule_object_delete, upload_concurrency=concurrency,
    )


def _delete_r2_object(object_key: str) -> None:
    endpoint, access, secret, bucket, _, _ = _storage_config()
    if object_key and storage.configured(endpoint, access, secret, bucket):
        storage.delete(object_key, client_factory=_r2_client, bucket=bucket or "")


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


async def _refresh_queue_statuses() -> None:
    """Push current position and ETA to every active transcription message."""
    for job in activity_store.get_active_transcription_jobs():
        if job["status"] == "processing":
            await _edit_status(job, tr(job["language"], "transcription_processing"))
            continue
        status = activity_store.get_transcription_queue_status(job["id"])
        if status and status.get("position"):
            await _edit_status(
                job,
                tr(job["language"], "transcription_queued_with_position", position=status["position"], eta_minutes=status["eta_minutes"]),
            )


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


async def _deliver_summary(job: dict[str, Any], summary: str, transcript: str, title: str, language: str) -> None:
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
            await bot.send_message(chat_id=job["chat_id"], text=summary[:4096])
            with artifact.open("rb") as document:
                await bot.send_document(
                    chat_id=job["chat_id"], document=document, filename=filename,
                    caption=tr(language, "transcription_ready", detected_language=language),
                    read_timeout=120, write_timeout=120,
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
        if self.request.retries < MAX_RETRIES:
            raise self.retry(exc=RuntimeError("Transcription job is not visible to the worker"), countdown=30)
        return {"status": "missing", "job_id": job_id}
    if job["status"] in {"completed", "cancelled"}:
        return {"status": job["status"], "job_id": job_id}
    claim = activity_store.claim_transcription_job(job_id)
    if claim is None:
        # Do not acknowledge a task when the durable state store is down. The
        # broker/reconciler must get another chance after the outage is fixed.
        raise RuntimeError("Transcription state database is temporarily unavailable")
    if not claim:
        LOG.info("event=transcription_duplicate_delivery_skipped job_id=%s status=%s", job_id, job["status"])
        return {"status": "already_processing", "job_id": job_id}
    job = activity_store.get_transcription_job(job_id) or job

    started = time.perf_counter()
    directory = Path(tempfile.mkdtemp(prefix="transcription-"))
    object_key: str | None = None
    asyncio.run(_refresh_queue_statuses())
    try:
        language = job["language"]
        is_summary = job.get("job_type") == "summary"
        activity_store.update_event(job.get("activity_id"), status="started", action="summarize" if is_summary else "transcribe")
        LOG.info("event=transcription_job_started job_id=%s", job_id)
        asyncio.run(_edit_status(job, tr(language, "downloading", fmt="mp3")))
        info, audio_file, _ = _download_sync(job["source_url"], "mp3", str(directory))
        activity_store.update_event(job.get("activity_id"), status="started", title=info.get("title"), duration_ms=int(float(info.get("duration") or 0) * 1000) if info.get("duration") else None)
        audio_url, object_key = _upload_to_r2(audio_file, info, "mp3")
        asyncio.run(_edit_status(job, tr(language, "summarization_processing" if is_summary else "transcription_processing")))
        result = transcribe_audio_url_sync(
            audio_url, str(info.get("title") or "Transcript"), info.get("duration"),
            summarize=is_summary, summary_language=language,
        )
        transcript = format_transcript(result)
        if is_summary:
            summary = result.get("summary")
            if not summary:
                raise RuntimeError("The summarization service returned an empty summary")
            asyncio.run(_deliver_summary(job, summary, transcript, str(result.get("title") or "Transcript"), language))
        else:
            asyncio.run(_deliver(job, transcript, str(result.get("title") or "Transcript"), language))
        activity_store.update_transcription_job(
            job_id, status="completed", processing_duration_seconds=time.perf_counter() - started,
        )
        asyncio.run(_refresh_queue_statuses())
        activity_store.update_event(job.get("activity_id"), status="completed", action="summarize" if is_summary else "transcribe", title=result.get("title"), duration_ms=int(float(result.get("duration") or 0) * 1000) if result.get("duration") else None)
        LOG.info("event=transcription_job_finished job_id=%s total_duration_seconds=%.2f", job_id, time.perf_counter() - started)
        return {"status": "completed", "job_id": job_id}
    except Exception as exc:
        if retryable(exc):
            countdown = retry_delay_seconds(self.request.retries)
            next_attempt = datetime.now(timezone.utc) + timedelta(seconds=countdown)
            activity_store.update_transcription_job(job_id, status="queued", error=str(exc), next_attempt_at=next_attempt)
            asyncio.run(_refresh_queue_statuses())
            LOG.warning("event=transcription_job_retry job_id=%s retry=%s error=%s", job_id, self.request.retries + 1, display_error(exc))
            if self.request.retries < MAX_RETRIES:
                raise self.retry(exc=exc, countdown=countdown)
            # Celery's per-task retry counter is finite. Leave the durable
            # database job queued; the bot reconciler will submit it again
            # after the longer cooldown and reset the Celery retry counter.
            cooldown = RETRY_AFTER_MAX_SECONDS
            activity_store.update_transcription_job(
                job_id, status="queued", error=str(exc),
                next_attempt_at=datetime.now(timezone.utc) + timedelta(seconds=cooldown),
            )
            try:
                asyncio.run(_edit_status(job, tr(job["language"], "transcription_retrying", retry_minutes=max(1, cooldown // 60))))
            except Exception:
                LOG.warning("event=transcription_retry_status_failed job_id=%s", job_id, exc_info=True)
            return {"status": "retry_wait", "job_id": job_id}
        activity_store.update_transcription_job(job_id, status="failed", error=str(exc))
        asyncio.run(_refresh_queue_statuses())
        activity_store.update_event(job.get("activity_id"), status="failed", action="summarize" if job.get("job_type") == "summary" else "transcribe", error=display_error(exc, job["language"]))
        try:
            asyncio.run(_edit_status(job, display_error(exc, job["language"])))
        except Exception:
            LOG.warning("event=transcription_failure_notification_failed job_id=%s", job_id, exc_info=True)
        LOG.exception("event=transcription_job_failed job_id=%s total_duration_seconds=%.2f", job_id, time.perf_counter() - started)
        raise
    finally:
        if object_key:
            try:
                _delete_r2_object(object_key)
            except Exception:
                LOG.warning("event=transcription_cleanup_failed job_id=%s", job_id, exc_info=True)
        shutil.rmtree(directory, ignore_errors=True)
