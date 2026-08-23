"""Best-effort cleanup for short-lived R2 download objects."""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

LOG = logging.getLogger("downloader_bot.r2_cleanup")


def schedule_object_delete(client_factory: Callable[[], Any], bucket: str, key: str, *, delay_seconds: int) -> None:
    """Schedule exact expiry cleanup; the periodic sweep covers restarts."""
    def delete() -> None:
        try:
            client_factory().delete_object(Bucket=bucket, Key=key)
            LOG.info("R2 cleanup removed expired object")
        except Exception:
            LOG.warning("Scheduled R2 object cleanup failed; periodic sweep will retry", exc_info=True)

    timer = threading.Timer(delay_seconds, delete)
    timer.daemon = True
    timer.start()


def delete_expired_objects(client: Any, bucket: str, *, prefix: str, retention_seconds: int) -> int:
    """Delete objects older than the link lifetime under one safe prefix."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=retention_seconds)
    expired_keys: list[str] = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            key = item.get("Key")
            modified = item.get("LastModified")
            if not isinstance(key, str) or not key.startswith(prefix) or not isinstance(modified, datetime):
                continue
            if modified.tzinfo is None:
                modified = modified.replace(tzinfo=timezone.utc)
            if modified <= cutoff:
                expired_keys.append(key)

    deleted = 0
    for offset in range(0, len(expired_keys), 1000):
        batch = expired_keys[offset:offset + 1000]
        response = client.delete_objects(
            Bucket=bucket,
            Delete={"Objects": [{"Key": key} for key in batch], "Quiet": True},
        )
        errors = response.get("Errors", [])
        deleted += len(batch) - len(errors)
        if errors:
            LOG.warning("R2 cleanup could not delete %s object(s)", len(errors))
    return deleted


async def cleanup_loop(
    client_factory: Callable[[], Any],
    bucket: str,
    *,
    prefix: str,
    retention_seconds: int,
    interval_seconds: int,
) -> None:
    """Sweep expired objects repeatedly; cancellation cleanly stops the loop."""
    loop = asyncio.get_running_loop()
    while True:
        try:
            deleted = await loop.run_in_executor(
                None,
                lambda: delete_expired_objects(
                    client_factory(),
                    bucket,
                    prefix=prefix,
                    retention_seconds=retention_seconds,
                ),
            )
            if deleted:
                LOG.info("R2 cleanup removed %s expired download object(s)", deleted)
        except asyncio.CancelledError:
            raise
        except Exception:
            LOG.warning("R2 cleanup sweep failed; retrying later", exc_info=True)
        await asyncio.sleep(interval_seconds)
