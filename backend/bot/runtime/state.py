"""Short-lived in-memory state owned by one Telegram bot process."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class LinkState:
    url: str
    chat_id: int
    user_id: int
    created_at: float
    title: str = "Video"
    duration: int | None = None
    activity_id: str | None = None


@dataclass(slots=True)
class PendingDelivery:
    directory: Path
    filename: Path
    chat_id: int
    user_id: int
    info: dict[str, Any]
    extension: str
    fmt: str
    size_bytes: int
    activity_id: str | None
    created_at: float


STATES: dict[str, LinkState] = {}
PENDING_DELIVERIES: dict[str, PendingDelivery] = {}
LANGUAGE_CACHE: dict[int, str] = {}
DOWNLOAD_LOCKS: dict[int, asyncio.Lock] = {}
SUPPORT_PROMPT_LAST_SHOWN: dict[tuple[int, int], float] = {}


def prune_link_states(*, ttl_seconds: int, max_entries: int) -> None:
    cutoff = time.monotonic() - ttl_seconds
    for key, state in list(STATES.items()):
        if state.created_at < cutoff:
            STATES.pop(key, None)
    if len(STATES) > max_entries:
        excess = len(STATES) - max_entries
        for key, _ in sorted(STATES.items(), key=lambda item: item[1].created_at)[:excess]:
            STATES.pop(key, None)


def prune_pending_deliveries(*, ttl_seconds: int) -> list[PendingDelivery]:
    cutoff = time.monotonic() - ttl_seconds
    expired: list[PendingDelivery] = []
    for key, pending in list(PENDING_DELIVERIES.items()):
        if pending.created_at < cutoff:
            PENDING_DELIVERIES.pop(key, None)
            expired.append(pending)
    return expired
