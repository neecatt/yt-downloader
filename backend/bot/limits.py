"""Small in-memory sliding-window limits for abuse and cost control."""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Hashable


class SlidingWindowLimiter:
    def __init__(self, max_keys: int = 10000):
        self._entries: dict[Hashable, deque[float]] = {}
        self._lock = threading.Lock()
        self._max_keys = max(100, max_keys)

    def allow(self, key: Hashable, *, limit: int, window_seconds: int, now: float | None = None) -> bool:
        if limit <= 0 or window_seconds <= 0:
            return False
        current = time.monotonic() if now is None else now
        cutoff = current - window_seconds
        with self._lock:
            entries = self._entries.setdefault(key, deque())
            while entries and entries[0] <= cutoff:
                entries.popleft()
            if len(entries) >= limit:
                return False
            entries.append(current)
            self._evict_empty()
            return True

    def _evict_empty(self) -> None:
        if len(self._entries) <= self._max_keys:
            return
        for key in list(self._entries):
            if not self._entries[key]:
                self._entries.pop(key, None)
                if len(self._entries) <= self._max_keys:
                    return
        oldest_key = min(self._entries, key=lambda candidate: self._entries[candidate][-1])
        self._entries.pop(oldest_key, None)
