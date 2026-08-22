from __future__ import annotations

import os
import threading
import uuid
import logging
from datetime import datetime, timezone
from typing import Any

_lock = threading.Lock()
LOG = logging.getLogger("downloader_bot")


def _database_url() -> str:
    return os.getenv("DATABASE_URL", "").strip()


def _connect():
    import psycopg
    return psycopg.connect(_database_url(), connect_timeout=10)


def enabled() -> bool:
    url = _database_url()
    if not url or "postgres:password@localhost" in url:
        return False
    try:
        import psycopg  # noqa: F401
    except ImportError:
        return False
    return True


def initialize() -> None:
    if not enabled():
        return
    try:
        with _lock, _connect() as connection:
            connection.execute("""
            CREATE TABLE IF NOT EXISTS activity_events (
                id TEXT PRIMARY KEY,
                telegram_username TEXT,
                telegram_display_name TEXT,
                chat_type TEXT,
                source_url TEXT NOT NULL,
                title TEXT,
                platform TEXT NOT NULL,
                action TEXT NOT NULL,
                format TEXT,
                status TEXT NOT NULL,
                delivery TEXT,
                size_bytes BIGINT,
                duration_ms BIGINT,
                error TEXT,
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL
            )
        """)
            connection.execute("CREATE INDEX IF NOT EXISTS idx_activity_created_at ON activity_events(created_at DESC)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_activity_status ON activity_events(status)")
    except Exception:
        LOG.warning("Activity database is unavailable; activity logging is temporarily disabled", exc_info=True)


def create_event(*, username: str | None, display_name: str | None, chat_type: str | None, source_url: str, title: str | None, platform: str, action: str, fmt: str | None = None) -> str | None:
    if not enabled():
        return None
    event_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    try:
        with _lock, _connect() as connection:
            connection.execute("INSERT INTO activity_events (id, telegram_username, telegram_display_name, chat_type, source_url, title, platform, action, format, status, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'started', %s, %s)", (event_id, username, display_name, chat_type, source_url, title, platform, action, fmt, now, now))
        return event_id
    except Exception:
        LOG.warning("Could not record activity event", exc_info=True)
        return None


def update_event(event_id: str | None, *, status: str, fmt: str | None = None, delivery: str | None = None, size_bytes: int | None = None, duration_ms: int | None = None, title: str | None = None, error: str | None = None) -> None:
    if not event_id:
        return
    now = datetime.now(timezone.utc)
    fields = ["status = %s", "updated_at = %s"]
    values: list[Any] = [status, now]
    for name, value in (("format", fmt), ("delivery", delivery), ("size_bytes", size_bytes), ("duration_ms", duration_ms), ("title", title), ("error", error)):
        if value is not None:
            fields.append(f"{name} = %s"); values.append(value)
    values.append(event_id)
    try:
        with _lock, _connect() as connection:
            connection.execute(f"UPDATE activity_events SET {', '.join(fields)} WHERE id = %s", values)
    except Exception:
        LOG.warning("Could not update activity event", exc_info=True)


def query_events(*, q: str | None = None, platform: str | None = None, status: str | None = None, page: int = 1, page_size: int = 25) -> dict[str, Any]:
    page = max(1, page); page_size = min(100, max(1, page_size)); clauses: list[str] = []; values: list[Any] = []
    if q:
        clauses.append("(telegram_username ILIKE %s OR telegram_display_name ILIKE %s OR source_url ILIKE %s OR title ILIKE %s)"); needle = f"%{q[:100]}%"; values.extend([needle] * 4)
    if platform: clauses.append("platform = %s"); values.append(platform[:40])
    if status: clauses.append("status = %s"); values.append(status[:20])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _lock, _connect() as connection:
        total = connection.execute(f"SELECT COUNT(*) FROM activity_events {where}", values).fetchone()[0]
        rows = connection.execute(f"SELECT * FROM activity_events {where} ORDER BY created_at DESC LIMIT %s OFFSET %s", [*values, page_size, (page - 1) * page_size]).fetchall()
        summary = connection.execute(f"SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE status = 'completed') AS completed, COUNT(*) FILTER (WHERE status = 'failed') AS failed, COUNT(DISTINCT COALESCE(telegram_username, telegram_display_name)) AS active_users, COALESCE(SUM(size_bytes), 0) AS total_bytes FROM activity_events {where}", values).fetchone()
    events = [{"id": row[0], "telegramUsername": row[1], "telegramDisplayName": row[2], "sourceUrl": row[4], "title": row[5], "platform": row[6], "action": row[7], "format": row[8], "status": row[9], "delivery": row[10], "sizeBytes": row[11], "durationMs": row[12], "error": row[13], "createdAt": row[14].isoformat()} for row in rows]
    return {"events": events, "summary": {"total": summary[0] or 0, "completed": summary[1] or 0, "failed": summary[2] or 0, "activeUsers": summary[3] or 0, "totalBytes": summary[4] or 0}, "page": page, "pageSize": page_size, "total": total}
