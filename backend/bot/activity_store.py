from __future__ import annotations

import os
import threading
import uuid
import logging
import re
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
                updated_at TIMESTAMPTZ NOT NULL,
                telegram_chat_id BIGINT
            )
        """)
            connection.execute("ALTER TABLE activity_events ADD COLUMN IF NOT EXISTS telegram_chat_id BIGINT")
            connection.execute("""
            CREATE TABLE IF NOT EXISTS bot_contacts (
                chat_id BIGINT PRIMARY KEY,
                telegram_username TEXT,
                telegram_display_name TEXT,
                chat_type TEXT,
                updated_at TIMESTAMPTZ NOT NULL,
                admin_read_at TIMESTAMPTZ,
                language_code TEXT
            )
            """)
            connection.execute("ALTER TABLE bot_contacts ADD COLUMN IF NOT EXISTS admin_read_at TIMESTAMPTZ")
            connection.execute("ALTER TABLE bot_contacts ADD COLUMN IF NOT EXISTS language_code TEXT")
            connection.execute("""
            CREATE TABLE IF NOT EXISTS bot_messages (
                id TEXT PRIMARY KEY,
                telegram_chat_id BIGINT NOT NULL,
                telegram_username TEXT,
                telegram_display_name TEXT,
                direction TEXT NOT NULL CHECK (direction IN ('inbound', 'outbound')),
                text TEXT NOT NULL,
                telegram_message_id BIGINT,
                delivered BOOLEAN NOT NULL DEFAULT TRUE,
                error TEXT,
                created_at TIMESTAMPTZ NOT NULL
            )
            """)
            connection.execute("""
            CREATE TABLE IF NOT EXISTS feedbacks (
                id TEXT PRIMARY KEY,
                telegram_chat_id BIGINT NOT NULL,
                telegram_username TEXT,
                telegram_display_name TEXT,
                feedback TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'reviewed')),
                created_at TIMESTAMPTZ NOT NULL,
                reviewed_at TIMESTAMPTZ
            )
            """)
            connection.execute("CREATE INDEX IF NOT EXISTS idx_activity_created_at ON activity_events(created_at DESC)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_activity_status ON activity_events(status)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_bot_messages_chat_created ON bot_messages(telegram_chat_id, created_at DESC)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_feedback_status_created ON feedbacks(status, created_at DESC)")
    except Exception:
        LOG.warning("Activity database is unavailable; activity logging is temporarily disabled", exc_info=True)


def create_event(*, username: str | None, display_name: str | None, chat_type: str | None, chat_id: int | None, source_url: str, title: str | None, platform: str, action: str, fmt: str | None = None) -> str | None:
    if not enabled():
        return None
    event_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    try:
        with _lock, _connect() as connection:
            connection.execute("INSERT INTO activity_events (id, telegram_username, telegram_display_name, chat_type, source_url, title, platform, action, format, status, created_at, updated_at, telegram_chat_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'started', %s, %s, %s)", (event_id, username, display_name, chat_type, source_url, title, platform, action, fmt, now, now, chat_id))
        return event_id
    except Exception:
        LOG.warning("Could not record activity event", exc_info=True)
        return None


def record_contact(*, chat_id: int, username: str | None, display_name: str | None, chat_type: str | None) -> None:
    if not enabled():
        return
    now = datetime.now(timezone.utc)
    try:
        with _lock, _connect() as connection:
            connection.execute(
                "INSERT INTO bot_contacts (chat_id, telegram_username, telegram_display_name, chat_type, updated_at) VALUES (%s, %s, %s, %s, %s) ON CONFLICT (chat_id) DO UPDATE SET telegram_username = EXCLUDED.telegram_username, telegram_display_name = EXCLUDED.telegram_display_name, chat_type = EXCLUDED.chat_type, updated_at = EXCLUDED.updated_at",
                (chat_id, username, display_name, chat_type, now),
            )
    except Exception:
        LOG.warning("Could not record bot contact", exc_info=True)


def get_language(chat_id: int) -> str | None:
    if not enabled():
        return None
    try:
        with _lock, _connect() as connection:
            row = connection.execute("SELECT language_code FROM bot_contacts WHERE chat_id = %s", (chat_id,)).fetchone()
        return row[0] if row else None
    except Exception:
        LOG.warning("Could not read chat language", exc_info=True)
        return None


def set_language(chat_id: int, language_code: str) -> None:
    if not enabled():
        return
    try:
        with _lock, _connect() as connection:
            connection.execute("UPDATE bot_contacts SET language_code = %s, updated_at = %s WHERE chat_id = %s", (language_code, datetime.now(timezone.utc), chat_id))
    except Exception:
        LOG.warning("Could not save chat language", exc_info=True)


def record_message(*, chat_id: int, username: str | None, display_name: str | None, direction: str, text: str, telegram_message_id: int | None = None, delivered: bool = True, error: str | None = None) -> str | None:
    """Store a text message exchanged in a private bot chat."""
    if not enabled() or direction not in {"inbound", "outbound"} or not text.strip():
        return None
    message_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    try:
        with _lock, _connect() as connection:
            connection.execute(
                "INSERT INTO bot_messages (id, telegram_chat_id, telegram_username, telegram_display_name, direction, text, telegram_message_id, delivered, error, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (message_id, chat_id, username, display_name, direction, text[:4096], telegram_message_id, delivered, error[:1000] if error else None, now),
            )
        return message_id
    except Exception:
        LOG.warning("Could not record chat message", exc_info=True)
        return None


def create_feedback(*, chat_id: int, username: str | None, display_name: str | None, feedback: str) -> str | None:
    if not enabled() or not feedback.strip():
        return None
    feedback_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    try:
        with _lock, _connect() as connection:
            connection.execute(
                "INSERT INTO feedbacks (id, telegram_chat_id, telegram_username, telegram_display_name, feedback, status, created_at) VALUES (%s, %s, %s, %s, %s, 'new', %s)",
                (feedback_id, chat_id, username, display_name, feedback[:4096], now),
            )
        return feedback_id
    except Exception:
        LOG.warning("Could not record feedback", exc_info=True)
        return None


def query_feedback(*, status: str | None = None, q: str | None = None, page: int = 1, page_size: int = 25) -> dict[str, Any]:
    if not enabled():
        return {"feedbacks": [], "page": page, "pageSize": page_size, "total": 0, "newCount": 0}
    page = max(1, page)
    page_size = min(100, max(1, page_size))
    clauses: list[str] = []
    values: list[Any] = []
    if status in {"new", "reviewed"}:
        clauses.append("status = %s")
        values.append(status)
    if q:
        needle = f"%{q[:100]}%"
        clauses.append("(telegram_username ILIKE %s OR telegram_display_name ILIKE %s OR feedback ILIKE %s)")
        values.extend([needle, needle, needle])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _lock, _connect() as connection:
        total = connection.execute(f"SELECT COUNT(*) FROM feedbacks {where}", values).fetchone()[0]
        rows = connection.execute(
            f"SELECT id, telegram_username, telegram_display_name, feedback, status, created_at, reviewed_at FROM feedbacks {where} ORDER BY created_at DESC LIMIT %s OFFSET %s",
            [*values, page_size, (page - 1) * page_size],
        ).fetchall()
        new_count = connection.execute("SELECT COUNT(*) FROM feedbacks WHERE status = 'new'").fetchone()[0]
    return {
        "feedbacks": [
            {"id": row[0], "telegramUsername": row[1], "telegramDisplayName": row[2], "feedback": row[3], "status": row[4], "createdAt": row[5].isoformat(), "reviewedAt": row[6].isoformat() if row[6] else None}
            for row in rows
        ],
        "page": page, "pageSize": page_size, "total": int(total), "newCount": int(new_count),
    }


def update_feedback_status(feedback_id: str, status: str) -> bool:
    if not enabled() or not re.fullmatch(r"[a-f0-9]{32}", feedback_id) or status not in {"new", "reviewed"}:
        return False
    reviewed_at = datetime.now(timezone.utc) if status == "reviewed" else None
    with _lock, _connect() as connection:
        cursor = connection.execute("UPDATE feedbacks SET status = %s, reviewed_at = %s WHERE id = %s", (status, reviewed_at, feedback_id))
        return cursor.rowcount > 0


def delete_feedback(feedback_id: str) -> bool:
    if not enabled() or not re.fullmatch(r"[a-f0-9]{32}", feedback_id):
        return False
    with _lock, _connect() as connection:
        cursor = connection.execute("DELETE FROM feedbacks WHERE id = %s", (feedback_id,))
        return cursor.rowcount > 0


def query_conversations(*, q: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    if not enabled():
        return []
    limit = min(100, max(1, limit))
    clauses: list[str] = []
    values: list[Any] = []
    if q:
        needle = f"%{q[:100]}%"
        clauses.append("(c.telegram_username ILIKE %s OR c.telegram_display_name ILIKE %s OR EXISTS (SELECT 1 FROM bot_messages sq WHERE sq.telegram_chat_id = c.chat_id AND sq.text ILIKE %s))")
        values.extend([needle, needle, needle])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _lock, _connect() as connection:
        rows = connection.execute(
            f"""
            SELECT c.chat_id, c.telegram_username, c.telegram_display_name, c.updated_at,
                   latest.text, latest.direction, latest.created_at,
                   COALESCE(unread.unread_count, 0)
            FROM bot_contacts c
            LEFT JOIN LATERAL (
                SELECT text, direction, created_at FROM bot_messages
                WHERE telegram_chat_id = c.chat_id ORDER BY created_at DESC LIMIT 1
            ) latest ON TRUE
            LEFT JOIN LATERAL (
                SELECT COUNT(*) AS unread_count FROM bot_messages
                WHERE telegram_chat_id = c.chat_id AND direction = 'inbound'
                  AND (c.admin_read_at IS NULL OR created_at > c.admin_read_at)
            ) unread ON TRUE
            {where}
            ORDER BY COALESCE(latest.created_at, c.updated_at) DESC
            LIMIT %s
            """,
            [*values, limit],
        ).fetchall()
    return [
        {
            "chatId": int(row[0]), "username": row[1], "displayName": row[2],
            "updatedAt": row[3].isoformat(), "lastText": row[4],
            "lastDirection": row[5], "lastMessageAt": row[6].isoformat() if row[6] else None,
            "unreadCount": int(row[7] or 0),
        }
        for row in rows
    ]


def query_messages(chat_id: int, *, limit: int = 100) -> list[dict[str, Any]]:
    if not enabled():
        return []
    limit = min(200, max(1, limit))
    with _lock, _connect() as connection:
        rows = connection.execute(
            "SELECT id, direction, text, delivered, error, created_at FROM bot_messages WHERE telegram_chat_id = %s ORDER BY created_at DESC LIMIT %s",
            (chat_id, limit),
        ).fetchall()
    return [
        {"id": row[0], "direction": row[1], "text": row[2], "delivered": bool(row[3]), "error": row[4], "createdAt": row[5].isoformat()}
        for row in reversed(rows)
    ]


def mark_conversation_read(chat_id: int) -> None:
    if not enabled():
        return
    try:
        with _lock, _connect() as connection:
            connection.execute("UPDATE bot_contacts SET admin_read_at = %s WHERE chat_id = %s", (datetime.now(timezone.utc), chat_id))
    except Exception:
        LOG.warning("Could not mark conversation read", exc_info=True)


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


def delete_events(event_ids: list[str]) -> int:
    """Delete only explicitly selected event IDs."""
    ids = [event_id for event_id in dict.fromkeys(event_ids) if re.fullmatch(r"[a-f0-9]{32}", event_id)]
    if not ids or not enabled():
        return 0
    placeholders = ", ".join(["%s"] * len(ids))
    with _lock, _connect() as connection:
        cursor = connection.execute(f"DELETE FROM activity_events WHERE id IN ({placeholders})", ids)
        return cursor.rowcount


def recipient_chat_ids(username: str | None = None) -> list[int]:
    """Return distinct private chat IDs for known users, newest records first."""
    if not enabled():
        return []
    normalized_username = None
    if username:
        normalized_username = username if username.startswith("@") else f"@{username}"
    with _lock, _connect() as connection:
        if normalized_username:
            rows = connection.execute(
                "SELECT chat_id FROM bot_contacts WHERE chat_type = 'private' AND LOWER(telegram_username) = LOWER(%s) UNION SELECT telegram_chat_id FROM activity_events WHERE chat_type = 'private' AND telegram_chat_id IS NOT NULL AND LOWER(telegram_username) = LOWER(%s) ORDER BY chat_id",
                (normalized_username, normalized_username),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT chat_id FROM bot_contacts WHERE chat_type = 'private' UNION SELECT telegram_chat_id FROM activity_events WHERE chat_type = 'private' AND telegram_chat_id IS NOT NULL ORDER BY chat_id",
            ).fetchall()
    return [int(row[0]) for row in rows]


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
    def as_int(value: Any, default: int | None = None) -> int | None:
        return default if value is None else int(value)

    events = [{"id": row[0], "telegramUsername": row[1], "telegramDisplayName": row[2], "sourceUrl": row[4], "title": row[5], "platform": row[6], "action": row[7], "format": row[8], "status": row[9], "delivery": row[10], "sizeBytes": as_int(row[11]), "durationMs": as_int(row[12]), "error": row[13], "createdAt": row[14].isoformat()} for row in rows]
    return {"events": events, "summary": {"total": as_int(summary[0], 0), "completed": as_int(summary[1], 0), "failed": as_int(summary[2], 0), "activeUsers": as_int(summary[3], 0), "totalBytes": as_int(summary[4], 0)}, "page": page, "pageSize": page_size, "total": as_int(total, 0)}
