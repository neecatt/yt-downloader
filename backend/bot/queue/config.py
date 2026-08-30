"""Celery broker and worker policy configuration."""

from __future__ import annotations

import os

from celery import Celery


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
    worker_prefetch_multiplier=1,
    broker_transport_options={
        "visibility_timeout": max(3600, int(os.getenv("CELERY_VISIBILITY_TIMEOUT_SECONDS", "21600"))),
    },
    result_expires=int(os.getenv("CELERY_RESULT_EXPIRES_SECONDS", "86400")),
    task_time_limit=max(3600, int(os.getenv("CELERY_TASK_TIME_LIMIT_SECONDS", "18000"))),
    task_soft_time_limit=max(1800, int(os.getenv("CELERY_SOFT_TIME_LIMIT_SECONDS", "17400"))),
)
