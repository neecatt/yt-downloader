"""PostgreSQL integration tests for durable monetization state.

Set TEST_DATABASE_URL to a disposable PostgreSQL database to run these tests.
Every run creates and removes its own randomly named schema; DATABASE_URL is
never used, which prevents accidental production database access.
"""

from __future__ import annotations

import os
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from backend.bot.config.settings import settings as app_settings
from backend.bot.persistence import monetization_store as store

try:
    import psycopg
    from psycopg import sql
except ImportError:  # pragma: no cover - unittest reports the skip reason
    psycopg = None
    sql = None


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "").strip()


class _ConcurrentLock:
    """No-op lock used to prove PostgreSQL, not the process lock, serializes work."""

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


@unittest.skipUnless(TEST_DATABASE_URL and psycopg, "set TEST_DATABASE_URL to a disposable PostgreSQL database")
class MonetizationPostgresIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = f"monetization_test_{uuid.uuid4().hex}"
        with psycopg.connect(TEST_DATABASE_URL) as connection:
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(cls.schema)))
        with cls.connect() as connection:
            connection.execute("""
                CREATE TABLE bot_contacts (
                    chat_id BIGINT PRIMARY KEY, telegram_username TEXT,
                    telegram_display_name TEXT, chat_type TEXT,
                    updated_at TIMESTAMPTZ NOT NULL
                )
            """)
            connection.execute("CREATE TABLE activity_events (id TEXT PRIMARY KEY, status TEXT NOT NULL)")
            connection.execute("CREATE TABLE transcription_jobs (id TEXT PRIMARY KEY, status TEXT NOT NULL)")
        configured = replace(app_settings.monetization, enabled=True, premium_enabled=True, rollout_percent=100)
        with patch.object(store, "enabled", return_value=True), patch.object(store, "_connect", side_effect=cls.connect), patch.object(store, "settings", SimpleNamespace(monetization=configured)):
            store.initialize()

    @classmethod
    def tearDownClass(cls):
        with psycopg.connect(TEST_DATABASE_URL) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(cls.schema)))

    @classmethod
    def connect(cls):
        return psycopg.connect(TEST_DATABASE_URL, options=f"-c search_path={cls.schema}")

    def setUp(self):
        with self.connect() as connection:
            connection.execute("TRUNCATE user_accounts CASCADE")
            connection.execute("TRUNCATE bot_contacts, activity_events, transcription_jobs")
        configured = replace(app_settings.monetization, enabled=True, premium_enabled=True, rollout_percent=100)
        self.patches = (
            patch.object(store, "enabled", return_value=True),
            patch.object(store, "_connect", side_effect=self.connect),
            patch.object(store, "settings", SimpleNamespace(monetization=configured)),
        )
        for active_patch in self.patches:
            active_patch.start()
            self.addCleanup(active_patch.stop)

    def account(self, user_id: int) -> dict:
        account = store.ensure_account(user_id=user_id, chat_id=user_id, username=f"@user{user_id}", display_name=f"User {user_id}")
        self.assertIsNotNone(account)
        return account

    def test_account_backfill_and_starter_grant_are_idempotent(self):
        now = datetime.now(timezone.utc)
        with self.connect() as connection:
            connection.execute("INSERT INTO bot_contacts VALUES (42, '@known', 'Known User', 'private', %s)", (now,))
        store.initialize()
        store.initialize()
        self.assertEqual(store.get_account(42)["credits"], 100)
        with self.connect() as connection:
            grants = connection.execute("SELECT COUNT(*) FROM credit_ledger WHERE telegram_user_id=42 AND reason='starter_grant'").fetchone()[0]
        self.assertEqual(grants, 1)

    def test_concurrent_duplicate_reservation_is_atomic_across_connections(self):
        self.account(7)
        with patch.object(store, "_LOCK", _ConcurrentLock()):
            with ThreadPoolExecutor(max_workers=10) as executor:
                reservations = list(executor.map(
                    lambda _: store.reserve(user_id=7, kind="download", idempotency_key="same-telegram-callback"),
                    range(20),
                ))
        self.assertEqual(len({reservation.id for reservation in reservations}), 1)
        account = store.get_account(7)
        self.assertEqual((account["credits"], account["reserved_credits"]), (100, 0))

    def test_settlement_release_and_stale_heartbeat_are_idempotent(self):
        self.account(7)
        completed = store.reserve(user_id=7, kind="download", idempotency_key="completed")
        self.assertTrue(store.settle(completed.id, size_bytes=123)["changed"])
        self.assertFalse(store.settle(completed.id)["changed"])

        interrupted = store.reserve(user_id=7, kind="download", idempotency_key="interrupted")
        self.assertTrue(store.release(interrupted.id, "delivery_failed"))
        self.assertFalse(store.release(interrupted.id, "duplicate"))

        active = store.reserve(user_id=7, kind="download", idempotency_key="active")
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=1)
        store.touch(active.id)
        self.assertFalse(store.release(active.id, "stale_reservation", updated_before=cutoff))
        account = store.get_account(7)
        self.assertEqual((account["credits"], account["reserved_credits"], account["successful_downloads"]), (100, 0, 1))

    def test_referral_qualifies_once_after_first_successful_operation(self):
        inviter = self.account(99)
        self.account(7)
        self.assertEqual(store.attach_referral(7, inviter["referral_code"]), "attached")
        reservation = store.reserve(user_id=7, kind="download", idempotency_key="referral-0")
        store.settle(reservation.id)
        self.assertEqual(store.get_account(99)["credits"], 150)
        self.assertEqual(store.get_account(7)["credits"], 150)
        self.assertEqual(store.referral_progress(99)["qualified"], 1)

    def test_payment_renewal_duplicate_and_refund_recalculate_access(self):
        self.account(7)
        payload = store.create_star_order(7)
        first_expiry = datetime.now(timezone.utc) + timedelta(days=30)
        renewal_expiry = first_expiry + timedelta(days=30)
        self.assertTrue(store.apply_star_payment(user_id=7, payload=payload, charge_id="first", amount=149, currency="XTR", expiration=first_expiry, recurring=True, first_recurring=True))
        self.assertFalse(store.apply_star_payment(user_id=7, payload=payload, charge_id="first", amount=149, currency="XTR", expiration=first_expiry, recurring=True, first_recurring=True))
        self.assertTrue(store.apply_star_payment(user_id=7, payload=payload, charge_id="renewal", amount=149, currency="XTR", expiration=renewal_expiry, recurring=True, first_recurring=False))
        self.assertEqual(store.get_account(7)["subscription_expires_at"], renewal_expiry)
        self.assertTrue(store.mark_refunded("renewal", 7))
        self.assertEqual(store.get_account(7)["subscription_expires_at"], first_expiry)

    def test_admin_updates_are_audited_and_cannot_spend_reserved_credit(self):
        self.account(7)
        store.reserve(user_id=7, kind="ai", idempotency_key="reserved")
        with self.assertRaisesRegex(ValueError, "reserved credits"):
            store.admin_update_user(7, credit_adjustment=-100, ai_trials=None, complimentary=None, reason="invalid reduction")
        updated = store.admin_update_user(7, credit_adjustment=5, ai_trials=1, complimentary=True, reason="support grant")
        self.assertEqual((updated["credits"], updated["ai_trials"], updated["complimentary"]), (105, 1, True))
        self.assertTrue(any(item["type"] == "admin_entitlement_update" for item in store.admin_history(7)))


if __name__ == "__main__":
    unittest.main()
