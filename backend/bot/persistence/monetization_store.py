"""Durable, idempotent entitlement, referral, and Telegram Stars accounting."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import threading
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any

from ..config.settings import MonetizationSettings, settings

LOG = logging.getLogger("downloader_bot")
_LOCK = threading.Lock()


class EntitlementUnavailable(RuntimeError):
    def __init__(self, reason: str, account: dict[str, Any] | None = None):
        super().__init__(reason)
        self.reason = reason
        self.account = account or {}


@dataclass(frozen=True, slots=True)
class Reservation:
    id: str
    status: str
    kind: str
    user_id: int


def _database_url() -> str:
    if os.getenv("YT_DOWNLOADER_TESTING", "").strip().lower() in {"1", "true", "yes", "on"}:
        return ""
    return os.getenv("DATABASE_URL", "").strip()


def _connect():
    import psycopg
    return psycopg.connect(_database_url(), connect_timeout=10)


def enabled() -> bool:
    if not _database_url() or "postgres:password@localhost" in _database_url():
        return False
    try:
        import psycopg  # noqa: F401
    except ImportError:
        return False
    return True


def _now() -> datetime:
    return datetime.now(timezone.utc)


def enforcement_enabled_for(user_id: int) -> bool:
    config = monetization_settings()
    if not config.enabled:
        return False
    if user_id in config.rollout_user_ids:
        return True
    bucket = int(hashlib.sha256(str(user_id).encode()).hexdigest()[:8], 16) % 100
    return bucket < config.rollout_percent


def _settings_row(config: MonetizationSettings) -> tuple[Any, ...]:
    return (
        True, config.enabled, config.starter_credits, config.ai_credit_cost, config.daily_download_limit, config.ai_trials,
        config.referral_inviter_reward, config.referral_invitee_reward,
        config.referral_required_downloads, config.referral_monthly_cap,
        config.premium_price_stars, config.stale_reservation_seconds,
        config.cost_alert_file_bytes // (1024 * 1024), config.rollout_percent,
        list(config.rollout_user_ids), _now(), "bootstrap",
        config.premium_enabled,
    )


def _row_to_settings(row: Any, base: MonetizationSettings) -> MonetizationSettings:
    return replace(
        base, enabled=bool(row[1]), starter_credits=int(row[2]), ai_credit_cost=int(row[3]), daily_download_limit=int(row[4]), ai_trials=int(row[5]),
        referral_inviter_reward=int(row[6]), referral_invitee_reward=int(row[7]),
        referral_required_downloads=int(row[8]), referral_monthly_cap=int(row[9]),
        premium_price_stars=int(row[10]), stale_reservation_seconds=int(row[11]),
        cost_alert_file_bytes=int(row[12]) * 1024 * 1024, rollout_percent=int(row[13]),
        rollout_user_ids=tuple(int(value) for value in (row[14] or ())),
        premium_enabled=bool(row[15]),
    )


def monetization_settings() -> MonetizationSettings:
    """Return the current persisted config, falling back safely to bootstrap defaults."""
    base = settings.monetization
    emergency_disabled = os.getenv("MONETIZATION_EMERGENCY_DISABLED", "").strip().lower() in {"1", "true", "yes", "on"}
    if not enabled():
        return replace(base, enabled=False) if emergency_disabled else base
    try:
        with _connect() as connection:
            row = connection.execute(
                "SELECT id,enabled,starter_credits,ai_credit_cost,daily_download_limit,ai_trials,referral_inviter_reward,referral_invitee_reward,"
                "referral_required_downloads,referral_monthly_cap,premium_price_stars,stale_reservation_seconds,"
                "cost_alert_file_mb,rollout_percent,rollout_user_ids,premium_enabled "
                "FROM monetization_config WHERE id=TRUE"
            ).fetchone()
        current = _row_to_settings(row, base) if row else base
        return replace(current, enabled=False) if emergency_disabled else current
    except Exception:
        LOG.warning("event=monetization_settings_read_failed_using_bootstrap")
        return replace(base, enabled=False) if emergency_disabled else base


def monetization_settings_dict(config: MonetizationSettings | None = None) -> dict[str, Any]:
    config = config or monetization_settings()
    return {
        "enabled": config.enabled, "starterCredits": config.starter_credits,
        "aiCreditCost": config.ai_credit_cost, "dailyDownloadLimit": config.daily_download_limit, "aiTrials": config.ai_trials, "referralInviterReward": config.referral_inviter_reward,
        "referralInviteeReward": config.referral_invitee_reward,
        "referralRequiredDownloads": config.referral_required_downloads,
        "referralMonthlyCap": config.referral_monthly_cap,
        "premiumPriceStars": config.premium_price_stars,
        "staleReservationSeconds": config.stale_reservation_seconds,
        "costAlertFileMb": config.cost_alert_file_bytes // (1024 * 1024),
        "rolloutPercent": config.rollout_percent,
        "rolloutUserIds": list(config.rollout_user_ids),
        "premiumEnabled": config.premium_enabled,
        "emergencyDisabled": os.getenv("MONETIZATION_EMERGENCY_DISABLED", "").strip().lower() in {"1", "true", "yes", "on"},
    }


_SETTING_RANGES = {
    "starter_credits": (0, 1000), "ai_credit_cost": (0, 1000), "daily_download_limit": (1, 500), "ai_trials": (0, 100),
    "referral_inviter_reward": (0, 1000), "referral_invitee_reward": (0, 1000),
    "referral_required_downloads": (1, 100), "referral_monthly_cap": (0, 100),
    "premium_price_stars": (1, 100000), "stale_reservation_seconds": (300, 86400),
    "cost_alert_file_mb": (1, 4096), "rollout_percent": (0, 100),
}


def update_monetization_settings(changes: dict[str, Any], *, reason: str, actor: str = "admin") -> dict[str, Any]:
    if not enabled():
        raise RuntimeError("Account database unavailable")
    if not 3 <= len(reason.strip()) <= 500 or any(ord(char) < 32 and char not in "\t\n\r" for char in reason):
        raise ValueError("A reason of 3 to 500 characters is required")
    allowed = {"enabled", "premium_enabled", *_SETTING_RANGES, "rollout_user_ids"}
    unknown = set(changes) - allowed
    if unknown:
        raise ValueError("Unknown monetization setting")
    for name, (minimum, maximum) in _SETTING_RANGES.items():
        if name in changes and (type(changes[name]) is not int or not minimum <= changes[name] <= maximum):
            raise ValueError(f"{name} is outside its safe range")
    if "enabled" in changes and type(changes["enabled"]) is not bool:
        raise ValueError("enabled must be a boolean")
    if "premium_enabled" in changes and type(changes["premium_enabled"]) is not bool:
        raise ValueError("premium_enabled must be a boolean")
    if "rollout_user_ids" in changes:
        values = changes["rollout_user_ids"]
        if not isinstance(values, list) or len(values) > 1000 or any(type(value) is not int or not 0 < value <= 9_223_372_036_854_775_807 for value in values):
            raise ValueError("rollout_user_ids must contain at most 1000 valid Telegram IDs")
        changes = {**changes, "rollout_user_ids": sorted(set(values))}
    now = _now()
    with _LOCK, _connect() as connection:
        row = connection.execute("SELECT enabled,starter_credits,ai_credit_cost,daily_download_limit,ai_trials,referral_inviter_reward,referral_invitee_reward,referral_required_downloads,referral_monthly_cap,premium_price_stars,stale_reservation_seconds,cost_alert_file_mb,rollout_percent,rollout_user_ids,premium_enabled FROM monetization_config WHERE id=TRUE FOR UPDATE").fetchone()
        if not row:
            raise RuntimeError("Monetization settings are not initialized")
        names = ("enabled", "starter_credits", "ai_credit_cost", "daily_download_limit", "ai_trials", "referral_inviter_reward", "referral_invitee_reward", "referral_required_downloads", "referral_monthly_cap", "premium_price_stars", "stale_reservation_seconds", "cost_alert_file_mb", "rollout_percent", "rollout_user_ids", "premium_enabled")
        current = dict(zip(names, row))
        current.update(changes)
        connection.execute("""UPDATE monetization_config SET enabled=%s,starter_credits=%s,ai_credit_cost=%s,daily_download_limit=%s,ai_trials=%s,
            referral_inviter_reward=%s,referral_invitee_reward=%s,referral_required_downloads=%s,
            referral_monthly_cap=%s,premium_price_stars=%s,stale_reservation_seconds=%s,
            cost_alert_file_mb=%s,rollout_percent=%s,rollout_user_ids=%s,premium_enabled=%s,updated_at=%s,updated_by=%s
            WHERE id=TRUE""", tuple(current[name] for name in names) + (now, actor))
        connection.execute("INSERT INTO monetization_settings_audit (id,changed,reason,actor,created_at) VALUES (%s,%s,%s,%s,%s)", (uuid.uuid4().hex, json.dumps(changes, sort_keys=True), reason.strip(), actor, now))
    return monetization_settings_dict(_row_to_settings((True, *[current[name] for name in names]), settings.monetization))


def monetization_settings_history(limit: int = 100) -> list[dict[str, Any]]:
    if not enabled():
        return []
    with _connect() as connection:
        rows = connection.execute(
            "SELECT changed,reason,actor,created_at FROM monetization_settings_audit ORDER BY created_at DESC LIMIT %s",
            (min(200, max(1, limit)),),
        ).fetchall()
    result = []
    for changed, reason, actor, created_at in rows:
        try:
            changed = json.loads(changed)
        except (TypeError, json.JSONDecodeError):
            changed = {"raw": str(changed)}
        result.append({"changed": changed, "reason": reason, "actor": actor, "createdAt": created_at.isoformat()})
    return result


def _row_to_account(row: Any) -> dict[str, Any]:
    expiry = row[11]
    premium = bool(row[10]) or bool(expiry and expiry > _now())
    return {
        "user_id": int(row[0]), "chat_id": int(row[1]) if row[1] is not None else None,
        "username": row[2], "display_name": row[3], "credits": int(row[4]),
        "reserved_credits": int(row[5]), "ai_trials": int(row[6]),
        "reserved_ai_trials": int(row[7]), "referral_code": row[8],
        "successful_downloads": int(row[9]), "complimentary": bool(row[10]),
        "subscription_expires_at": expiry, "subscription_cancelled": bool(row[12]),
        "premium": premium, "created_at": row[13], "updated_at": row[14], "last_seen_at": row[15],
    }


_ACCOUNT_COLUMNS = """telegram_user_id, telegram_chat_id, telegram_username, telegram_display_name,
credit_balance, reserved_credits, ai_trials_remaining, reserved_ai_trials, referral_code,
successful_downloads, complimentary_unlimited, subscription_expires_at,
subscription_cancelled, created_at, updated_at, last_seen_at"""


def initialize() -> None:
    if not enabled():
        return
    now = _now()
    try:
        with _LOCK, _connect() as connection:
            # Serialize schema/backfill work across Railway bot, worker, and API
            # processes. A process-local lock is not enough during deployments.
            connection.execute("SELECT pg_advisory_xact_lock(884617203)")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS monetization_config (
                    id BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (id=TRUE),
                    enabled BOOLEAN NOT NULL,
                    starter_credits INTEGER NOT NULL CHECK (starter_credits BETWEEN 0 AND 1000),
                    ai_trials INTEGER NOT NULL CHECK (ai_trials BETWEEN 0 AND 100),
                    referral_inviter_reward INTEGER NOT NULL CHECK (referral_inviter_reward BETWEEN 0 AND 1000),
                    referral_invitee_reward INTEGER NOT NULL CHECK (referral_invitee_reward BETWEEN 0 AND 1000),
                    ai_credit_cost INTEGER NOT NULL DEFAULT 5 CHECK (ai_credit_cost BETWEEN 0 AND 1000),
                    daily_download_limit INTEGER NOT NULL DEFAULT 15 CHECK (daily_download_limit BETWEEN 1 AND 500),
                    referral_required_downloads INTEGER NOT NULL CHECK (referral_required_downloads BETWEEN 1 AND 100),
                    referral_monthly_cap INTEGER NOT NULL CHECK (referral_monthly_cap BETWEEN 0 AND 100),
                    premium_price_stars INTEGER NOT NULL CHECK (premium_price_stars BETWEEN 1 AND 100000),
                    stale_reservation_seconds INTEGER NOT NULL CHECK (stale_reservation_seconds BETWEEN 300 AND 86400),
                    cost_alert_file_mb INTEGER NOT NULL CHECK (cost_alert_file_mb BETWEEN 1 AND 4096),
                    rollout_percent INTEGER NOT NULL CHECK (rollout_percent BETWEEN 0 AND 100),
                    rollout_user_ids BIGINT[] NOT NULL DEFAULT '{}',
                    updated_at TIMESTAMPTZ NOT NULL,
                    updated_by TEXT NOT NULL,
                    premium_enabled BOOLEAN NOT NULL DEFAULT FALSE
                )
            """)
            connection.execute("ALTER TABLE monetization_config ADD COLUMN IF NOT EXISTS ai_credit_cost INTEGER NOT NULL DEFAULT 5")
            connection.execute("ALTER TABLE monetization_config ADD COLUMN IF NOT EXISTS daily_download_limit INTEGER NOT NULL DEFAULT 15")
            connection.execute("ALTER TABLE monetization_config ADD COLUMN IF NOT EXISTS premium_enabled BOOLEAN NOT NULL DEFAULT FALSE")
            # Move the original pre-launch defaults forward once while keeping
            # any values an administrator already customized.
            connection.execute("""
                UPDATE monetization_config
                SET starter_credits=100, referral_inviter_reward=50,
                    referral_invitee_reward=50, referral_required_downloads=1
                WHERE starter_credits=10 AND referral_inviter_reward=10
                  AND referral_invitee_reward=5 AND referral_required_downloads=2
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS monetization_settings_audit (
                    id TEXT PRIMARY KEY, changed TEXT NOT NULL, reason TEXT NOT NULL,
                    actor TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL
                )
            """)
            connection.execute("""
                INSERT INTO monetization_config
                (id,enabled,starter_credits,ai_credit_cost,daily_download_limit,ai_trials,referral_inviter_reward,referral_invitee_reward,
                 referral_required_downloads,referral_monthly_cap,premium_price_stars,stale_reservation_seconds,
                 cost_alert_file_mb,rollout_percent,rollout_user_ids,updated_at,updated_by,premium_enabled)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (id) DO NOTHING
            """, _settings_row(settings.monetization))
            connection.execute("""
                CREATE TABLE IF NOT EXISTS user_accounts (
                    telegram_user_id BIGINT PRIMARY KEY,
                    telegram_chat_id BIGINT,
                    telegram_username TEXT,
                    telegram_display_name TEXT,
                    credit_balance INTEGER NOT NULL CHECK (credit_balance >= 0),
                    reserved_credits INTEGER NOT NULL DEFAULT 0 CHECK (reserved_credits >= 0),
                    ai_trials_remaining INTEGER NOT NULL CHECK (ai_trials_remaining >= 0),
                    reserved_ai_trials INTEGER NOT NULL DEFAULT 0 CHECK (reserved_ai_trials >= 0),
                    referral_code TEXT NOT NULL UNIQUE,
                    successful_downloads INTEGER NOT NULL DEFAULT 0 CHECK (successful_downloads >= 0),
                    complimentary_unlimited BOOLEAN NOT NULL DEFAULT FALSE,
                    subscription_expires_at TIMESTAMPTZ,
                    subscription_cancelled BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL,
                    last_seen_at TIMESTAMPTZ NOT NULL
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS entitlement_operations (
                    id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    telegram_user_id BIGINT NOT NULL REFERENCES user_accounts(telegram_user_id),
                    kind TEXT NOT NULL CHECK (kind IN ('download', 'ai')),
                    status TEXT NOT NULL CHECK (status IN ('reserved', 'settled', 'released', 'bypassed')),
                    entitlement_source TEXT NOT NULL DEFAULT 'shadow',
                    credit_cost INTEGER NOT NULL DEFAULT 0,
                    ai_trial_cost INTEGER NOT NULL DEFAULT 0,
                    activity_id TEXT,
                    transcription_job_id TEXT,
                    size_bytes BIGINT,
                    duration_ms BIGINT,
                    processing_duration_ms BIGINT,
                    release_reason TEXT,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL,
                    settled_at TIMESTAMPTZ,
                    released_at TIMESTAMPTZ
                )
            """)
            connection.execute("ALTER TABLE entitlement_operations ADD COLUMN IF NOT EXISTS entitlement_source TEXT NOT NULL DEFAULT 'shadow'")
            connection.execute("ALTER TABLE entitlement_operations ADD COLUMN IF NOT EXISTS processing_duration_ms BIGINT")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS credit_ledger (
                    id TEXT PRIMARY KEY,
                    telegram_user_id BIGINT NOT NULL REFERENCES user_accounts(telegram_user_id),
                    delta INTEGER NOT NULL,
                    balance_after INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    operation_id TEXT,
                    actor TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS referrals (
                    invited_user_id BIGINT PRIMARY KEY REFERENCES user_accounts(telegram_user_id),
                    inviter_user_id BIGINT NOT NULL REFERENCES user_accounts(telegram_user_id),
                    status TEXT NOT NULL CHECK (status IN ('pending', 'qualified', 'rejected')),
                    suspicious_reason TEXT,
                    created_at TIMESTAMPTZ NOT NULL,
                    qualified_at TIMESTAMPTZ
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS star_orders (
                    payload_hash TEXT PRIMARY KEY,
                    telegram_user_id BIGINT NOT NULL REFERENCES user_accounts(telegram_user_id),
                    amount INTEGER NOT NULL,
                    currency TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('pending', 'paid', 'expired')),
                    created_at TIMESTAMPTZ NOT NULL,
                    paid_at TIMESTAMPTZ
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS star_payments (
                    telegram_payment_charge_id TEXT PRIMARY KEY,
                    telegram_user_id BIGINT NOT NULL REFERENCES user_accounts(telegram_user_id),
                    payload_hash TEXT NOT NULL,
                    amount INTEGER NOT NULL,
                    currency TEXT NOT NULL,
                    subscription_expires_at TIMESTAMPTZ,
                    is_recurring BOOLEAN NOT NULL DEFAULT FALSE,
                    is_first_recurring BOOLEAN NOT NULL DEFAULT FALSE,
                    refunded_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS entitlement_audit (
                    id TEXT PRIMARY KEY,
                    telegram_user_id BIGINT NOT NULL REFERENCES user_accounts(telegram_user_id),
                    event_type TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    details TEXT,
                    created_at TIMESTAMPTZ NOT NULL
                )
            """)
            connection.execute("CREATE INDEX IF NOT EXISTS idx_accounts_last_seen ON user_accounts(last_seen_at DESC)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_operations_user_created ON entitlement_operations(telegram_user_id, created_at DESC)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_referrals_inviter_status ON referrals(inviter_user_id, status, qualified_at)")
            connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_single_starter_grant ON credit_ledger(telegram_user_id, reason) WHERE reason='starter_grant'")
            # Private Telegram chats use the user ID as their chat ID. Existing
            # contacts get exactly the same starter grant as newly seen users.
            connection.execute("""
                INSERT INTO user_accounts (
                    telegram_user_id, telegram_chat_id, telegram_username, telegram_display_name,
                    credit_balance, ai_trials_remaining, referral_code, created_at, updated_at, last_seen_at
                )
                SELECT chat_id, chat_id, telegram_username, telegram_display_name, %s, %s,
                       SUBSTRING(MD5(chat_id::text || RANDOM()::text) FROM 1 FOR 12), %s, %s, updated_at
                FROM bot_contacts WHERE chat_type = 'private'
                ON CONFLICT (telegram_user_id) DO NOTHING
            """, (settings.monetization.starter_credits, settings.monetization.ai_trials, now, now))
            connection.execute("""
                INSERT INTO credit_ledger (id,telegram_user_id,delta,balance_after,reason,operation_id,actor,created_at)
                SELECT MD5(telegram_user_id::text || RANDOM()::text),telegram_user_id,%s,credit_balance,'starter_grant',NULL,'system',created_at
                FROM user_accounts ON CONFLICT DO NOTHING
            """, (settings.monetization.starter_credits,))
    except Exception as exc:
        LOG.exception("event=monetization_database_initialization_failed")
        raise RuntimeError("Monetization database initialization failed") from exc


def ensure_account(*, user_id: int, chat_id: int | None, username: str | None, display_name: str | None) -> dict[str, Any] | None:
    if not enabled() or user_id <= 0:
        return None
    now = _now()
    config = monetization_settings()
    code = secrets.token_urlsafe(9).replace("-", "").replace("_", "")[:12].lower()
    with _LOCK, _connect() as connection:
        connection.execute("""
            INSERT INTO user_accounts (
                telegram_user_id, telegram_chat_id, telegram_username, telegram_display_name,
                credit_balance, ai_trials_remaining, referral_code, created_at, updated_at, last_seen_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (telegram_user_id) DO UPDATE SET
                telegram_chat_id = COALESCE(EXCLUDED.telegram_chat_id, user_accounts.telegram_chat_id),
                telegram_username = EXCLUDED.telegram_username,
                telegram_display_name = EXCLUDED.telegram_display_name,
                updated_at = EXCLUDED.updated_at,
                last_seen_at = EXCLUDED.last_seen_at
        """, (user_id, chat_id, username[:64] if username else None, display_name[:256] if display_name else None,
        config.starter_credits, config.ai_trials, code, now, now, now))
        connection.execute("""
            INSERT INTO credit_ledger (id,telegram_user_id,delta,balance_after,reason,operation_id,actor,created_at)
            SELECT %s,telegram_user_id,%s,credit_balance,'starter_grant',NULL,'system',created_at
            FROM user_accounts WHERE telegram_user_id=%s ON CONFLICT DO NOTHING
        """, (uuid.uuid4().hex, config.starter_credits, user_id))
        row = connection.execute(f"SELECT {_ACCOUNT_COLUMNS} FROM user_accounts WHERE telegram_user_id = %s", (user_id,)).fetchone()
    return _row_to_account(row) if row else None


def get_account(user_id: int) -> dict[str, Any] | None:
    if not enabled() or user_id <= 0:
        return None
    with _connect() as connection:
        row = connection.execute(f"SELECT {_ACCOUNT_COLUMNS} FROM user_accounts WHERE telegram_user_id = %s", (user_id,)).fetchone()
    return _row_to_account(row) if row else None


def attach_referral(invited_user_id: int, referral_code: str) -> str:
    """Attach an inviter once. Returns attached, existing, invalid, self, or ineligible."""
    if not enabled() or invited_user_id <= 0 or not referral_code:
        return "invalid"
    now = _now()
    with _LOCK, _connect() as connection:
        invitee = connection.execute(
            "SELECT telegram_user_id, successful_downloads, created_at FROM user_accounts WHERE telegram_user_id = %s FOR UPDATE",
            (invited_user_id,),
        ).fetchone()
        inviter = connection.execute(
            "SELECT telegram_user_id FROM user_accounts WHERE referral_code = %s", (referral_code.lower()[:32],)
        ).fetchone()
        if not invitee or not inviter:
            LOG.warning("event=referral_attempt_invalid invited_user_id=%s", invited_user_id)
            return "invalid"
        if int(inviter[0]) == invited_user_id:
            connection.execute("INSERT INTO entitlement_audit VALUES (%s,%s,'suspicious_referral','Self-referral attempt','system',NULL,%s)", (uuid.uuid4().hex, invited_user_id, now))
            LOG.warning("event=referral_attempt_self user_id=%s", invited_user_id)
            return "self"
        existing = connection.execute("SELECT inviter_user_id FROM referrals WHERE invited_user_id = %s", (invited_user_id,)).fetchone()
        if existing:
            LOG.info("event=referral_attempt_duplicate invited_user_id=%s", invited_user_id)
            return "existing"
        if int(invitee[1]) > 0 or now - invitee[2] > timedelta(hours=24):
            connection.execute("INSERT INTO entitlement_audit VALUES (%s,%s,'suspicious_referral','Late referral assignment attempt','system',NULL,%s)", (uuid.uuid4().hex, invited_user_id, now))
            LOG.warning("event=referral_attempt_ineligible invited_user_id=%s", invited_user_id)
            return "ineligible"
        connection.execute("INSERT INTO referrals (invited_user_id, inviter_user_id, status, created_at) VALUES (%s,%s,'pending',%s)", (invited_user_id, int(inviter[0]), now))
    LOG.info("event=referral_attached inviter_id=%s invitee_id=%s", int(inviter[0]), invited_user_id)
    return "attached"


def reserve(*, user_id: int, kind: str, idempotency_key: str, activity_id: str | None = None) -> Reservation:
    if kind not in {"download", "ai"} or user_id <= 0 or not idempotency_key:
        raise ValueError("Invalid entitlement reservation")
    if not enabled():
        if monetization_settings().enabled:
            raise EntitlementUnavailable("account_service")
        # Local/test mode and a disabled rollout cannot enforce without state.
        return Reservation(uuid.uuid4().hex, "bypassed", kind, user_id)
    now = _now()
    config = monetization_settings()
    with _LOCK, _connect() as connection:
        # A database lock makes duplicate callbacks idempotent even when more
        # than one Railway replica receives the same logical operation.
        connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (idempotency_key[:200],))
        existing = connection.execute(
            "SELECT id, status, kind, telegram_user_id FROM entitlement_operations WHERE idempotency_key = %s",
            (idempotency_key[:200],),
        ).fetchone()
        if existing:
            return Reservation(existing[0], existing[1], existing[2], int(existing[3]))
        row = connection.execute(
            f"SELECT {_ACCOUNT_COLUMNS} FROM user_accounts WHERE telegram_user_id = %s FOR UPDATE", (user_id,)
        ).fetchone()
        if not row:
            raise EntitlementUnavailable("account_missing")
        account = _row_to_account(row)
        operation_id = uuid.uuid4().hex
        premium = account["premium"]
        status = "bypassed" if premium or not enforcement_enabled_for(user_id) else "reserved"
        source = ("complimentary" if account["complimentary"] else "premium" if premium else
                  "shadow" if status == "bypassed" else "credit")
        # Downloads are free in the launch model. AI/transcription work uses
        # the configured credit cost and is reserved before queueing.
        credit_cost = config.ai_credit_cost if kind == "ai" and status == "reserved" else 0
        ai_cost = 0
        if credit_cost and account["credits"] - account["reserved_credits"] < credit_cost:
            LOG.warning("event=credit_deduction_rejected user_id=%s kind=%s required=%s available=%s", user_id, kind, credit_cost, account["credits"] - account["reserved_credits"])
            raise EntitlementUnavailable("credits", account)
        if credit_cost:
            connection.execute("UPDATE user_accounts SET reserved_credits=reserved_credits+%s, updated_at=%s WHERE telegram_user_id=%s", (credit_cost, now, user_id))
        connection.execute("""
            INSERT INTO entitlement_operations
            (id,idempotency_key,telegram_user_id,kind,status,entitlement_source,credit_cost,ai_trial_cost,activity_id,created_at,updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (operation_id, idempotency_key[:200], user_id, kind, status, source, credit_cost, ai_cost, activity_id, now, now))
    LOG.info("event=entitlement_reserved user_id=%s kind=%s status=%s operation_id=%s", user_id, kind, status, operation_id)
    return Reservation(operation_id, status, kind, user_id)


def link_transcription_job(operation_id: str, job_id: str) -> None:
    if enabled() and operation_id and job_id:
        with _connect() as connection:
            connection.execute("UPDATE entitlement_operations SET transcription_job_id=%s, updated_at=%s WHERE id=%s", (job_id, _now(), operation_id))


def touch(operation_id: str | None) -> None:
    """Refresh an active reservation heartbeat without changing entitlement."""
    if enabled() and operation_id:
        with _connect() as connection:
            connection.execute(
                "UPDATE entitlement_operations SET updated_at=%s WHERE id=%s AND status='reserved'",
                (_now(), operation_id),
            )


def _qualify_referral(connection: Any, user_id: int, now: datetime, config: MonetizationSettings | None = None) -> dict[str, int] | None:
    config = config or monetization_settings()
    referral = connection.execute(
        "SELECT inviter_user_id FROM referrals WHERE invited_user_id=%s AND status='pending' FOR UPDATE", (user_id,)
    ).fetchone()
    if not referral:
        return None
    successful_operations = connection.execute(
        "SELECT COUNT(*) FROM entitlement_operations WHERE telegram_user_id=%s AND status='settled'", (user_id,)
    ).fetchone()[0]
    if successful_operations < config.referral_required_downloads:
        return None
    inviter_id = int(referral[0])
    # Serialize qualifications for the same inviter across bot/worker
    # processes so the rolling cap cannot be exceeded by concurrent jobs.
    connection.execute("SELECT pg_advisory_xact_lock(%s)", (inviter_id,))
    cutoff = now - timedelta(days=30)
    qualified = connection.execute(
        "SELECT COUNT(*) FROM referrals WHERE inviter_user_id=%s AND status='qualified' AND qualified_at >= %s", (inviter_id, cutoff)
    ).fetchone()[0]
    if qualified >= config.referral_monthly_cap:
        connection.execute("UPDATE referrals SET status='rejected', suspicious_reason='rolling_30_day_cap' WHERE invited_user_id=%s", (user_id,))
        return None
    rewards = ((inviter_id, config.referral_inviter_reward, "referral_inviter"),
               (user_id, config.referral_invitee_reward, "referral_invitee"))
    for rewarded_id, amount, reason in rewards:
        balance = connection.execute(
            "UPDATE user_accounts SET credit_balance=credit_balance+%s, updated_at=%s WHERE telegram_user_id=%s RETURNING credit_balance",
            (amount, now, rewarded_id),
        ).fetchone()[0]
        connection.execute("INSERT INTO credit_ledger VALUES (%s,%s,%s,%s,%s,NULL,'system',%s)", (uuid.uuid4().hex, rewarded_id, amount, balance, reason, now))
        LOG.info("event=referral_reward_granted user_id=%s amount=%s reason=%s", rewarded_id, amount, reason)
    connection.execute("UPDATE referrals SET status='qualified', qualified_at=%s WHERE invited_user_id=%s", (now, user_id))
    LOG.info("event=referral_qualified inviter_id=%s invitee_id=%s", inviter_id, user_id)
    return {"inviter_user_id": inviter_id, "invitee_user_id": user_id,
            "inviter_credits": config.referral_inviter_reward,
            "invitee_credits": config.referral_invitee_reward}


def settle(operation_id: str, *, size_bytes: int | None = None, duration_ms: int | None = None, processing_duration_ms: int | None = None) -> dict[str, Any]:
    if not enabled() or not operation_id:
        return {"changed": False}
    now = _now()
    config = monetization_settings()
    reward = None
    with _LOCK, _connect() as connection:
        row = connection.execute(
            "SELECT telegram_user_id,kind,status,credit_cost,ai_trial_cost FROM entitlement_operations WHERE id=%s FOR UPDATE", (operation_id,)
        ).fetchone()
        if not row or row[2] in {"settled", "released"}:
            return {"changed": False, "status": row[2] if row else "missing"}
        user_id, kind, status, credit_cost, ai_cost = int(row[0]), row[1], row[2], int(row[3]), int(row[4])
        if status == "reserved":
            account = connection.execute(
                "UPDATE user_accounts SET credit_balance=credit_balance-%s,reserved_credits=reserved_credits-%s,reserved_ai_trials=reserved_ai_trials-%s,updated_at=%s WHERE telegram_user_id=%s RETURNING credit_balance",
                (credit_cost, credit_cost, ai_cost, now, user_id),
            ).fetchone()
            if credit_cost:
                reason = "successful_ai" if kind == "ai" else "successful_delivery"
                connection.execute("INSERT INTO credit_ledger VALUES (%s,%s,%s,%s,%s,%s,'system',%s)", (uuid.uuid4().hex, user_id, -credit_cost, account[0], reason, operation_id, now))
                LOG.info("event=credit_deducted user_id=%s amount=%s reason=%s operation_id=%s", user_id, credit_cost, reason, operation_id)
        connection.execute("UPDATE entitlement_operations SET status='settled',size_bytes=%s,duration_ms=%s,processing_duration_ms=%s,settled_at=%s,updated_at=%s WHERE id=%s", (size_bytes, duration_ms, processing_duration_ms, now, now, operation_id))
        if kind == "download":
            connection.execute("UPDATE user_accounts SET successful_downloads=successful_downloads+1,updated_at=%s WHERE telegram_user_id=%s", (now, user_id))
        reward = _qualify_referral(connection, user_id, now, config)
    LOG.info("event=entitlement_settled user_id=%s kind=%s operation_id=%s size_bytes=%s", user_id, kind, operation_id, size_bytes)
    if size_bytes and size_bytes >= config.cost_alert_file_bytes:
        LOG.warning("event=cost_alert_large_delivery user_id=%s operation_id=%s size_bytes=%s", user_id, operation_id, size_bytes)
    return {"changed": True, "status": "settled", "referral_reward": reward}


def release(operation_id: str | None, reason: str, *, updated_before: datetime | None = None) -> bool:
    if not enabled() or not operation_id:
        return False
    now = _now()
    with _LOCK, _connect() as connection:
        row = connection.execute(
            "SELECT telegram_user_id,status,credit_cost,ai_trial_cost,updated_at FROM entitlement_operations WHERE id=%s FOR UPDATE", (operation_id,)
        ).fetchone()
        if not row or row[1] != "reserved":
            return False
        if updated_before is not None and row[4] >= updated_before:
            return False
        user_id, _, credit_cost, ai_cost = int(row[0]), row[1], int(row[2]), int(row[3])
        connection.execute(
            "UPDATE user_accounts SET reserved_credits=reserved_credits-%s,ai_trials_remaining=ai_trials_remaining+%s,reserved_ai_trials=reserved_ai_trials-%s,updated_at=%s WHERE telegram_user_id=%s",
            (credit_cost, ai_cost, ai_cost, now, user_id),
        )
        connection.execute("UPDATE entitlement_operations SET status='released',release_reason=%s,released_at=%s,updated_at=%s WHERE id=%s", (reason[:300], now, now, operation_id))
    LOG.info("event=entitlement_released user_id=%s operation_id=%s reason=%s", user_id, operation_id, reason[:80])
    return True


def release_stale() -> int:
    """Release abandoned downloads and AI reservations whose durable job ended."""
    if not enabled():
        return 0
    cutoff = _now() - timedelta(seconds=monetization_settings().stale_reservation_seconds)
    with _connect() as connection:
        rows = connection.execute("""
            SELECT o.id,o.kind,j.status,a.status FROM entitlement_operations o
            LEFT JOIN transcription_jobs j ON j.id=o.transcription_job_id
            LEFT JOIN activity_events a ON a.id=o.activity_id
            WHERE o.status='reserved' AND o.updated_at < %s
              AND (o.kind='download' OR j.id IS NULL OR j.status IN ('failed','cancelled','completed'))
            LIMIT 500
        """, (cutoff,)).fetchall()
    changed = 0
    for operation_id, kind, job_status, activity_status in rows:
        if (kind == "ai" and job_status == "completed") or (kind == "download" and activity_status == "completed"):
            changed += int(bool(settle(operation_id).get("changed")))
        else:
            changed += int(release(operation_id, "stale_reservation", updated_before=cutoff))
    return changed


def referral_progress(user_id: int) -> dict[str, Any]:
    if not enabled():
        return {"invited": 0, "qualified": 0, "pending": 0}
    with _connect() as connection:
        counts = connection.execute("SELECT COUNT(*),COUNT(*) FILTER (WHERE status='qualified'),COUNT(*) FILTER (WHERE status='pending') FROM referrals WHERE inviter_user_id=%s", (user_id,)).fetchone()
        own = connection.execute("SELECT inviter_user_id,status FROM referrals WHERE invited_user_id=%s", (user_id,)).fetchone()
    return {"invited": int(counts[0]), "qualified": int(counts[1]), "pending": int(counts[2]), "own_referral": own[1] if own else None}


def create_star_order(user_id: int) -> str:
    if not monetization_settings().premium_enabled:
        raise ValueError("Premium checkout is disabled")
    payload = f"premium:{user_id}:{secrets.token_urlsafe(24)}"
    digest = hashlib.sha256(payload.encode()).hexdigest()
    with _LOCK, _connect() as connection:
        account = connection.execute(
            "SELECT complimentary_unlimited,subscription_expires_at FROM user_accounts WHERE telegram_user_id=%s FOR UPDATE",
            (user_id,),
        ).fetchone()
        if not account or account[0] or (account[1] and account[1] > _now()):
            raise ValueError("Premium is already active or the account is unavailable")
        connection.execute("UPDATE star_orders SET status='expired' WHERE telegram_user_id=%s AND status='pending'", (user_id,))
        connection.execute("INSERT INTO star_orders VALUES (%s,%s,%s,'XTR','pending',%s,NULL)", (digest, user_id, monetization_settings().premium_price_stars, _now()))
    return payload


def validate_star_order(payload: str, user_id: int, amount: int, currency: str) -> bool:
    if not enabled() or not monetization_settings().enabled or not monetization_settings().premium_enabled or not payload:
        return False
    digest = hashlib.sha256(payload.encode()).hexdigest()
    with _connect() as connection:
        row = connection.execute("SELECT telegram_user_id,amount,currency,status,created_at FROM star_orders WHERE payload_hash=%s", (digest,)).fetchone()
    return bool(row and int(row[0]) == user_id and int(row[1]) == amount and row[2] == currency == "XTR" and row[3] == "pending" and _now() - row[4] < timedelta(hours=1))


def apply_star_payment(*, user_id: int, payload: str, charge_id: str, amount: int, currency: str,
                       expiration: datetime | None, recurring: bool, first_recurring: bool) -> bool:
    if not enabled() or not monetization_settings().premium_enabled or not charge_id:
        return False
    now = _now()
    digest = hashlib.sha256(payload.encode()).hexdigest()
    with _LOCK, _connect() as connection:
        order = connection.execute("SELECT telegram_user_id,amount,currency,status FROM star_orders WHERE payload_hash=%s FOR UPDATE", (digest,)).fetchone()
        if not order or int(order[0]) != user_id or int(order[1]) != amount or order[2] != currency or currency != "XTR":
            raise ValueError("Payment does not match its order")
        if connection.execute("SELECT 1 FROM star_payments WHERE telegram_payment_charge_id=%s", (charge_id,)).fetchone():
            return False
        if not recurring or expiration is None or expiration.tzinfo is None or expiration <= now:
            raise ValueError("Subscription payment is missing a valid Telegram expiration date")
        if order[3] != "pending" and first_recurring:
            raise ValueError("Initial subscription order was already paid")
        expiry = expiration
        connection.execute("INSERT INTO star_payments VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NULL,%s)", (charge_id, user_id, digest, amount, currency, expiry, recurring, first_recurring, now))
        connection.execute("UPDATE star_orders SET status='paid',paid_at=%s WHERE payload_hash=%s", (now, digest))
        connection.execute("UPDATE user_accounts SET subscription_expires_at=GREATEST(COALESCE(subscription_expires_at,%s),%s),subscription_cancelled=FALSE,updated_at=%s WHERE telegram_user_id=%s", (expiry, expiry, now, user_id))
        connection.execute("INSERT INTO entitlement_audit VALUES (%s,%s,'payment_received','Telegram Stars subscription payment','telegram',%s,%s)", (uuid.uuid4().hex, user_id, f"{amount} XTR", now))
    return True


def mark_refunded(charge_id: str, user_id: int) -> bool:
    if not enabled():
        return False
    now = _now()
    with _LOCK, _connect() as connection:
        row = connection.execute("UPDATE star_payments SET refunded_at=%s WHERE telegram_payment_charge_id=%s AND telegram_user_id=%s AND refunded_at IS NULL RETURNING subscription_expires_at", (now, charge_id, user_id)).fetchone()
        if not row:
            return False
        active = connection.execute("SELECT MAX(subscription_expires_at) FROM star_payments WHERE telegram_user_id=%s AND refunded_at IS NULL", (user_id,)).fetchone()[0]
        connection.execute("UPDATE user_accounts SET subscription_expires_at=%s,updated_at=%s WHERE telegram_user_id=%s", (active, now, user_id))
        connection.execute("INSERT INTO entitlement_audit VALUES (%s,%s,'payment_refunded','Telegram Stars payment refunded','telegram',NULL,%s)", (uuid.uuid4().hex, user_id, now))
    return True


def mark_subscription_cancelled(user_id: int, cancelled: bool = True) -> None:
    if enabled():
        with _connect() as connection:
            connection.execute("UPDATE user_accounts SET subscription_cancelled=%s,updated_at=%s WHERE telegram_user_id=%s", (cancelled, _now(), user_id))


def latest_active_charge(user_id: int) -> str | None:
    if not enabled():
        return None
    with _connect() as connection:
        row = connection.execute(
            """SELECT telegram_payment_charge_id FROM star_payments
               WHERE telegram_user_id=%s AND refunded_at IS NULL
                 AND payload_hash=(SELECT payload_hash FROM star_payments WHERE telegram_user_id=%s AND refunded_at IS NULL AND subscription_expires_at>NOW() ORDER BY subscription_expires_at DESC LIMIT 1)
               ORDER BY is_first_recurring DESC, created_at ASC LIMIT 1""",
            (user_id, user_id),
        ).fetchone()
    return row[0] if row else None


def admin_query_users(*, q: str | None, access: str | None, page: int, page_size: int) -> dict[str, Any]:
    if not enabled():
        return {"users": [], "page": page, "pageSize": page_size, "total": 0}
    clauses, values = [], []
    if q:
        clauses.append("(telegram_user_id::text=%s OR telegram_username ILIKE %s OR telegram_display_name ILIKE %s)")
        values.extend([q, f"%{q}%", f"%{q}%"])
    if access == "free": clauses.append("complimentary_unlimited=FALSE AND (subscription_expires_at IS NULL OR subscription_expires_at<=NOW())")
    elif access == "subscribed": clauses.append("subscription_expires_at>NOW() AND complimentary_unlimited=FALSE")
    elif access == "complimentary": clauses.append("complimentary_unlimited=TRUE")
    elif access == "low_credit": clauses.append("(credit_balance-reserved_credits)<=2 AND complimentary_unlimited=FALSE AND (subscription_expires_at IS NULL OR subscription_expires_at<=NOW())")
    elif access == "ai_exhausted": clauses.append("ai_trials_remaining=0 AND complimentary_unlimited=FALSE AND (subscription_expires_at IS NULL OR subscription_expires_at<=NOW())")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    offset = (page - 1) * page_size
    with _connect() as connection:
        total = int(connection.execute(f"SELECT COUNT(*) FROM user_accounts {where}", values).fetchone()[0])
        rows = connection.execute(f"""SELECT {_ACCOUNT_COLUMNS},
            (SELECT COUNT(*) FROM referrals r WHERE r.inviter_user_id=user_accounts.telegram_user_id AND r.status='qualified'),
            (SELECT COUNT(*) FROM referrals r WHERE r.inviter_user_id=user_accounts.telegram_user_id AND r.status='pending'),
            ((SELECT COUNT(*) FROM referrals r WHERE (r.inviter_user_id=user_accounts.telegram_user_id OR r.invited_user_id=user_accounts.telegram_user_id) AND r.suspicious_reason IS NOT NULL) +
             (SELECT COUNT(*) FROM entitlement_audit ea WHERE ea.telegram_user_id=user_accounts.telegram_user_id AND ea.event_type='suspicious_referral')),
            (SELECT COUNT(*) FROM entitlement_operations o WHERE o.telegram_user_id=user_accounts.telegram_user_id AND o.status='settled')
            FROM user_accounts {where} ORDER BY last_seen_at DESC LIMIT %s OFFSET %s""", (*values, page_size, offset)).fetchall()
    users=[]
    for row in rows:
        account=_row_to_account(row[:16]); account["qualified_referrals"]=int(row[16]); account["pending_referrals"]=int(row[17]); account["suspicious_referrals"]=int(row[18]); account["successful_operations"]=int(row[19])
        for key in ("subscription_expires_at", "created_at", "updated_at", "last_seen_at"):
            account[key] = account[key].isoformat() if account[key] else None
        users.append(account)
    return {"users": users, "page": page, "pageSize": page_size, "total": total}


def admin_update_user(user_id: int, *, credit_adjustment: int | None, ai_trials: int | None,
                      complimentary: bool | None, reason: str, actor: str = "admin") -> dict[str, Any] | None:
    if not enabled():
        return None
    now = _now()
    with _LOCK, _connect() as connection:
        row = connection.execute(f"SELECT {_ACCOUNT_COLUMNS} FROM user_accounts WHERE telegram_user_id=%s FOR UPDATE", (user_id,)).fetchone()
        if not row: return None
        account = _row_to_account(row)
        if credit_adjustment is not None:
            new_balance = account["credits"] + credit_adjustment
            if new_balance < account["reserved_credits"] or new_balance > 1_000_000: raise ValueError("Credit balance cannot be below reserved credits or above 1000000")
            connection.execute("UPDATE user_accounts SET credit_balance=%s,updated_at=%s WHERE telegram_user_id=%s", (new_balance, now, user_id))
            connection.execute("INSERT INTO credit_ledger VALUES (%s,%s,%s,%s,'admin_adjustment',NULL,%s,%s)", (uuid.uuid4().hex, user_id, credit_adjustment, new_balance, actor, now))
        if ai_trials is not None:
            if account["reserved_ai_trials"]:
                raise ValueError("AI trials cannot be changed while an AI operation is reserved")
            connection.execute("UPDATE user_accounts SET ai_trials_remaining=%s,updated_at=%s WHERE telegram_user_id=%s", (ai_trials, now, user_id))
        if complimentary is not None:
            connection.execute("UPDATE user_accounts SET complimentary_unlimited=%s,updated_at=%s WHERE telegram_user_id=%s", (complimentary, now, user_id))
        details = f"credits={credit_adjustment};ai_trials={ai_trials};complimentary={complimentary}"
        connection.execute("INSERT INTO entitlement_audit VALUES (%s,%s,'admin_entitlement_update',%s,%s,%s,%s)", (uuid.uuid4().hex, user_id, reason, actor, details, now))
        row = connection.execute(f"SELECT {_ACCOUNT_COLUMNS} FROM user_accounts WHERE telegram_user_id=%s", (user_id,)).fetchone()
    account = _row_to_account(row)
    for key in ("subscription_expires_at", "created_at", "updated_at", "last_seen_at"):
        account[key] = account[key].isoformat() if account[key] else None
    return account


def admin_history(user_id: int, limit: int = 100) -> list[dict[str, Any]]:
    if not enabled(): return []
    with _connect() as connection:
        rows = connection.execute("""
            SELECT event_type,reason,actor,details,created_at FROM entitlement_audit WHERE telegram_user_id=%s
            UNION ALL
            SELECT 'credit',reason,actor,('delta='||delta::text||';balance='||balance_after::text),created_at FROM credit_ledger WHERE telegram_user_id=%s
            UNION ALL
            SELECT 'operation',kind||':'||status,'system',('source='||entitlement_source||';size_bytes='||COALESCE(size_bytes,0)::text),created_at FROM entitlement_operations WHERE telegram_user_id=%s
            UNION ALL
            SELECT 'payment',CASE WHEN refunded_at IS NULL THEN 'received' ELSE 'refunded' END,'telegram',(amount::text||' '||currency||';expires='||COALESCE(subscription_expires_at::text,'none')),created_at FROM star_payments WHERE telegram_user_id=%s
            UNION ALL
            SELECT 'referral',status,'system',('inviter='||inviter_user_id::text||';flag='||COALESCE(suspicious_reason,'none')),created_at FROM referrals WHERE invited_user_id=%s
            ORDER BY created_at DESC LIMIT %s
        """, (user_id, user_id, user_id, user_id, user_id, min(200, max(1, limit)))).fetchall()
    return [{"type":r[0],"reason":r[1],"actor":r[2],"details":r[3],"createdAt":r[4].isoformat()} for r in rows]


def admin_usage(days: int = 30) -> dict[str, Any]:
    """Return aggregate product usage for the private operations dashboard."""
    if not enabled():
        return {"totals": {}, "daily": []}
    days = min(365, max(1, int(days)))
    cutoff = _now() - timedelta(days=days)
    with _connect() as connection:
        totals = connection.execute("""
            SELECT
              (SELECT COUNT(*) FROM user_accounts),
              (SELECT COUNT(*) FROM user_accounts WHERE created_at >= %s),
              COUNT(*) FILTER (WHERE o.status='settled'),
              COUNT(*) FILTER (WHERE o.status='settled' AND o.kind='download'),
              COUNT(*) FILTER (WHERE o.status='settled' AND o.kind='ai'),
              COUNT(*) FILTER (WHERE o.status='settled' AND a.action='transcribe'),
              COUNT(*) FILTER (WHERE o.status='settled' AND a.action='summarize'),
              COALESCE((SELECT SUM(delta) FROM credit_ledger WHERE delta > 0 AND created_at >= %s), 0),
              COALESCE((SELECT SUM(-delta) FROM credit_ledger WHERE delta < 0 AND created_at >= %s), 0),
              (SELECT COUNT(*) FROM referrals WHERE status='qualified' AND qualified_at >= %s)
            FROM entitlement_operations o
            LEFT JOIN activity_events a ON a.id=o.activity_id
            WHERE o.created_at >= %s
        """, (cutoff, cutoff, cutoff, cutoff, cutoff)).fetchone()
        daily_rows = connection.execute("""
            SELECT DATE(o.created_at), COUNT(*) FILTER (WHERE o.status='settled'),
                   COUNT(*) FILTER (WHERE o.status='settled' AND o.kind='ai'),
                   COUNT(*) FILTER (WHERE o.status='settled' AND a.action='summarize')
            FROM entitlement_operations o LEFT JOIN activity_events a ON a.id=o.activity_id
            WHERE o.created_at >= %s GROUP BY DATE(o.created_at) ORDER BY DATE(o.created_at)
        """, (cutoff,)).fetchall()
    keys = ("users", "newUsers", "successfulOperations", "downloads", "aiRequests", "transcriptions", "summaries", "creditsEarned", "creditsSpent", "qualifiedReferrals")
    return {"totals": dict(zip(keys, (int(value or 0) for value in totals))), "daily": [
        {"date": row[0].isoformat(), "successfulOperations": int(row[1] or 0), "aiRequests": int(row[2] or 0), "summaries": int(row[3] or 0)}
        for row in daily_rows
    ]}


def admin_credit_overview(*, q: str | None, page: int, page_size: int) -> dict[str, Any]:
    """Paginated credit/referral view with aggregate balances."""
    if not enabled():
        return {"users": [], "page": page, "pageSize": page_size, "total": 0, "summary": {}}
    clauses, values = [], []
    if q:
        clauses.append("(u.telegram_user_id::text=%s OR u.telegram_username ILIKE %s OR u.telegram_display_name ILIKE %s)")
        values.extend([q, f"%{q}%", f"%{q}%"])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    offset = (page - 1) * page_size
    with _connect() as connection:
        total = int(connection.execute(f"SELECT COUNT(*) FROM user_accounts u {where}", values).fetchone()[0])
        summary = connection.execute("""
            SELECT COUNT(*), COALESCE(SUM(credit_balance),0), COALESCE(SUM(reserved_credits),0),
                   COALESCE((SELECT SUM(delta) FROM credit_ledger WHERE delta > 0),0),
                   COALESCE((SELECT SUM(-delta) FROM credit_ledger WHERE delta < 0),0),
                   (SELECT COUNT(*) FROM referrals WHERE status='qualified'),
                   (SELECT COUNT(*) FROM referrals WHERE status='pending')
            FROM user_accounts
        """).fetchone()
        rows = connection.execute(f"""
            SELECT u.telegram_user_id,u.telegram_username,u.telegram_display_name,u.credit_balance,u.reserved_credits,
                   u.created_at,u.last_seen_at,
                   (SELECT COUNT(*) FROM referrals r WHERE r.inviter_user_id=u.telegram_user_id AND r.status='qualified'),
                   (SELECT COUNT(*) FROM referrals r WHERE r.inviter_user_id=u.telegram_user_id AND r.status='pending'),
                   (SELECT COALESCE(SUM(delta),0) FROM credit_ledger l WHERE l.telegram_user_id=u.telegram_user_id AND l.delta > 0),
                   (SELECT COALESCE(SUM(-delta),0) FROM credit_ledger l WHERE l.telegram_user_id=u.telegram_user_id AND l.delta < 0)
            FROM user_accounts u {where} ORDER BY u.last_seen_at DESC LIMIT %s OFFSET %s
        """, (*values, page_size, offset)).fetchall()
    return {
        "users": [{"userId": int(row[0]), "username": row[1], "displayName": row[2], "credits": int(row[3]), "reserved": int(row[4]), "createdAt": row[5].isoformat(), "lastSeenAt": row[6].isoformat(), "qualifiedReferrals": int(row[7]), "pendingReferrals": int(row[8]), "earned": int(row[9]), "spent": int(row[10])} for row in rows],
        "page": page, "pageSize": page_size, "total": total,
        "summary": {"users": int(summary[0]), "credits": int(summary[1]), "reserved": int(summary[2]), "earned": int(summary[3]), "spent": int(summary[4]), "qualifiedReferrals": int(summary[5]), "pendingReferrals": int(summary[6])},
    }


def admin_referrals(*, status: str | None, page: int, page_size: int) -> dict[str, Any]:
    if not enabled():
        return {"referrals": [], "page": page, "pageSize": page_size, "total": 0}
    clauses, values = [], []
    if status:
        clauses.append("r.status=%s"); values.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    offset = (page - 1) * page_size
    with _connect() as connection:
        total = int(connection.execute(f"SELECT COUNT(*) FROM referrals r {where}", values).fetchone()[0])
        rows = connection.execute(f"""
          SELECT r.inviter_user_id,r.invited_user_id,r.status,r.suspicious_reason,r.created_at,r.qualified_at,
                 i.telegram_username,e.telegram_username
          FROM referrals r JOIN user_accounts i ON i.telegram_user_id=r.inviter_user_id
          JOIN user_accounts e ON e.telegram_user_id=r.invited_user_id {where}
          ORDER BY r.created_at DESC LIMIT %s OFFSET %s
        """, (*values, page_size, offset)).fetchall()
    return {"referrals": [{"inviterId": int(r[0]), "inviteeId": int(r[1]), "status": r[2], "suspiciousReason": r[3], "createdAt": r[4].isoformat(), "qualifiedAt": r[5].isoformat() if r[5] else None, "inviterUsername": r[6], "inviteeUsername": r[7]} for r in rows], "page": page, "pageSize": page_size, "total": total}


def admin_transactions(*, q: str | None, page: int, page_size: int) -> dict[str, Any]:
    if not enabled():
        return {"transactions": [], "page": page, "pageSize": page_size, "total": 0}
    clauses, values = [], []
    if q:
        clauses.append("(l.telegram_user_id::text=%s OR u.telegram_username ILIKE %s OR u.telegram_display_name ILIKE %s OR l.reason ILIKE %s OR l.actor ILIKE %s)")
        values.extend([q, f"%{q}%", f"%{q}%", f"%{q}%", f"%{q}%"])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    offset = (page - 1) * page_size
    with _connect() as connection:
        total = int(connection.execute(f"SELECT COUNT(*) FROM credit_ledger l LEFT JOIN user_accounts u ON u.telegram_user_id=l.telegram_user_id {where}", values).fetchone()[0])
        rows = connection.execute(f"""
          SELECT l.id,l.telegram_user_id,u.telegram_username,u.telegram_display_name,l.delta,l.balance_after,l.reason,l.operation_id,l.actor,l.created_at
          FROM credit_ledger l LEFT JOIN user_accounts u ON u.telegram_user_id=l.telegram_user_id {where}
          ORDER BY l.created_at DESC LIMIT %s OFFSET %s
        """, (*values, page_size, offset)).fetchall()
    return {"transactions": [{"id": r[0], "userId": int(r[1]), "username": r[2], "displayName": r[3], "delta": int(r[4]), "balanceAfter": int(r[5]), "reason": r[6], "operationId": r[7], "actor": r[8], "createdAt": r[9].isoformat()} for r in rows], "page": page, "pageSize": page_size, "total": total}
