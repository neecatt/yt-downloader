"""Celery broker and worker policy configuration."""

from __future__ import annotations

import os

from celery import Celery

from ..config.settings import settings


def redis_url() -> str:
    return os.getenv("REDIS_URL", "").strip()


def configured() -> bool:
    return redis_url().startswith(("redis://", "rediss://"))


app = Celery("yt_downloader", broker=redis_url(), backend=redis_url())
app.conf.update(
    task_default_queue="transcription",
    task_routes={"transcription.process": {"queue": "transcription"}},
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    broker_connection_retry_on_startup=True,
    task_publish_retry=True,
    task_publish_retry_policy={"max_retries": 5, "interval_start": 1, "interval_step": 2, "interval_max": 10},
    worker_prefetch_multiplier=1,
    broker_transport_options={
        "visibility_timeout": settings.queue.visibility_timeout_seconds,
    },
    result_expires=settings.queue.result_expires_seconds,
    task_time_limit=settings.queue.task_time_limit_seconds,
    task_soft_time_limit=settings.queue.soft_time_limit_seconds,
)
