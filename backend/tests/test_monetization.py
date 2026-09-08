from __future__ import annotations

import asyncio
import hashlib
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

os.environ["YT_DOWNLOADER_TESTING"] = "1"
os.environ["DATABASE_URL"] = ""

from backend.bot.config.settings import load_settings, settings as app_settings
from backend.bot.i18n import tr
from backend.bot.persistence import monetization_store as store
from backend.bot.telegram import monetization
from backend.bot.api.admin import create_app
import backend.main as bot


class Cursor:
    def __init__(self, row=None):
        self._row = row
        self.rowcount = 1

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._row or []


class ReservationDatabase:
    """Small transactional double for the reservation state machine."""

    def __init__(self, *, credits=10, trials=2, complimentary=False, expiry=None):
        self.credits = credits
        self.trials = trials
        self.reserved_credits = 0
        self.reserved_trials = 0
        self.downloads = 0
        self.complimentary = complimentary
        self.expiry = expiry
        self.operations: dict[str, dict] = {}
        self.idempotency: dict[str, str] = {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def account_row(self):
        now = datetime.now(timezone.utc)
        return (7, 7, "@user", "User", self.credits, self.reserved_credits, self.trials,
                self.reserved_trials, "code", self.downloads, self.complimentary,
                self.expiry, False, now, now, now)

    def execute(self, sql, params=()):
        normalized = " ".join(sql.split())
        if "FROM entitlement_operations WHERE idempotency_key" in normalized:
            operation_id = self.idempotency.get(params[0])
            operation = self.operations.get(operation_id) if operation_id else None
            return Cursor((operation_id, operation["status"], operation["kind"], 7) if operation else None)
        if "FROM user_accounts WHERE telegram_user_id = %s FOR UPDATE" in normalized:
            return Cursor(self.account_row())
        if normalized.startswith("SELECT pg_advisory_xact_lock(hashtextextended"):
            return Cursor((None,))
        if normalized.startswith("UPDATE user_accounts SET reserved_credits=reserved_credits+"):
            self.reserved_credits += params[0]; return Cursor()
        if normalized.startswith("UPDATE user_accounts SET ai_trials_remaining=ai_trials_remaining-1"):
            self.trials -= 1; self.reserved_trials += 1; return Cursor()
        if normalized.startswith("INSERT INTO credit_ledger"):
            return Cursor()
        if normalized.startswith("INSERT INTO entitlement_operations"):
            operation_id, key, _user, kind, status, _source, credit_cost, ai_cost, *_ = params
            self.operations[operation_id] = {"status": status, "kind": kind, "credit": credit_cost, "ai": ai_cost}
            self.idempotency[key] = operation_id
            return Cursor()
        if "FROM entitlement_operations WHERE id=%s FOR UPDATE" in normalized:
            operation = self.operations.get(params[0])
            if not operation:
                return Cursor(None)
            if normalized.startswith("SELECT telegram_user_id,status"):
                return Cursor((7, operation["status"], operation["credit"], operation["ai"], datetime.now(timezone.utc) - timedelta(hours=3)))
            return Cursor((7, operation["kind"], operation["status"], operation["credit"], operation["ai"]))
        if normalized.startswith("UPDATE user_accounts SET credit_balance=credit_balance-"):
            credit, reserved, ai = params[0], params[1], params[2]
            self.credits -= credit; self.reserved_credits -= reserved; self.reserved_trials -= ai
            return Cursor((self.credits,))
        if normalized.startswith("UPDATE entitlement_operations SET status='settled'"):
            self.operations[params[-1]]["status"] = "settled"; return Cursor()
        if normalized.startswith("UPDATE user_accounts SET successful_downloads=successful_downloads+1"):
            self.downloads += 1; return Cursor()
        if "FROM referrals WHERE invited_user_id" in normalized:
            return Cursor(None)
        if normalized.startswith("UPDATE user_accounts SET reserved_credits=reserved_credits-"):
            credit, ai, reserved_ai = params[0], params[1], params[2]
            self.reserved_credits -= credit; self.trials += ai; self.reserved_trials -= reserved_ai
            return Cursor()
        if normalized.startswith("UPDATE entitlement_operations SET status='released'"):
            self.operations[params[-1]]["status"] = "released"; return Cursor()
        raise AssertionError(f"Unexpected SQL: {normalized}")


def fake_settings(*, enabled=True, premium_enabled=True):
    return SimpleNamespace(monetization=replace(app_settings.monetization, enabled=enabled, premium_enabled=premium_enabled))


class ReservationTests(unittest.TestCase):
    def test_concurrent_duplicate_reservations_charge_once(self):
        database = ReservationDatabase(credits=10)
        with patch.object(store, "enabled", return_value=True), patch.object(store, "_connect", return_value=database), patch.object(store, "settings", fake_settings()):
            with ThreadPoolExecutor(max_workers=8) as executor:
                reservations = list(executor.map(
                    lambda _: store.reserve(user_id=7, kind="download", idempotency_key="callback:one"),
                    range(20),
                ))
        self.assertEqual(database.credits, 10)
        self.assertEqual(database.reserved_credits, 0)
        self.assertEqual(len({item.id for item in reservations}), 1)

    def test_failed_operation_releases_reserved_credit_idempotently(self):
        database = ReservationDatabase(credits=1)
        with patch.object(store, "enabled", return_value=True), patch.object(store, "_connect", return_value=database), patch.object(store, "settings", fake_settings()):
            reservation = store.reserve(user_id=7, kind="download", idempotency_key="download:failure")
            self.assertTrue(store.release(reservation.id, "delivery_failed"))
            self.assertFalse(store.release(reservation.id, "duplicate_failure"))
        self.assertEqual((database.credits, database.reserved_credits), (1, 0))

    def test_success_settles_without_returning_credit(self):
        database = ReservationDatabase(credits=1)
        with patch.object(store, "enabled", return_value=True), patch.object(store, "_connect", return_value=database), patch.object(store, "settings", fake_settings()):
            reservation = store.reserve(user_id=7, kind="download", idempotency_key="download:success")
            first = store.settle(reservation.id, size_bytes=123)
            second = store.settle(reservation.id, size_bytes=123)
        self.assertTrue(first["changed"])
        self.assertFalse(second["changed"])
        self.assertEqual((database.credits, database.reserved_credits, database.downloads), (1, 0, 1))

    def test_ai_trial_is_shared_and_released_on_failure(self):
        database = ReservationDatabase(credits=10, trials=2)
        with patch.object(store, "enabled", return_value=True), patch.object(store, "_connect", return_value=database), patch.object(store, "settings", fake_settings()):
            reservation = store.reserve(user_id=7, kind="ai", idempotency_key="summary:one")
            self.assertEqual((database.credits, database.reserved_credits), (10, 5))
            store.release(reservation.id, "permanent_failure")
        self.assertEqual((database.credits, database.reserved_credits), (10, 0))

    def test_premium_bypasses_credit_and_trial_consumption(self):
        database = ReservationDatabase(credits=0, trials=0, complimentary=True)
        with patch.object(store, "enabled", return_value=True), patch.object(store, "_connect", return_value=database), patch.object(store, "settings", fake_settings()):
            download = store.reserve(user_id=7, kind="download", idempotency_key="premium:download")
            ai = store.reserve(user_id=7, kind="ai", idempotency_key="premium:ai")
        self.assertEqual(download.status, "bypassed")
        self.assertEqual(ai.status, "bypassed")
        self.assertEqual((database.credits, database.trials), (0, 0))

    def test_exhausted_balances_are_rejected(self):
        database = ReservationDatabase(credits=0, trials=0)
        with patch.object(store, "enabled", return_value=True), patch.object(store, "_connect", return_value=database), patch.object(store, "settings", fake_settings()):
            self.assertEqual(store.reserve(user_id=7, kind="download", idempotency_key="none").status, "reserved")
            with self.assertRaisesRegex(store.EntitlementUnavailable, "credits"):
                store.reserve(user_id=7, kind="ai", idempotency_key="none-ai")

    def test_stale_recovery_settles_completed_and_releases_interrupted_work(self):
        class Database:
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def execute(self, _sql, _params=()):
                return Cursor([
                    ("download-success", "download", None, "completed"),
                    ("download-crash", "download", None, "started"),
                    ("ai-success", "ai", "completed", "completed"),
                    ("ai-failure", "ai", "failed", "failed"),
                ])

        with (
            patch.object(store, "enabled", return_value=True),
            patch.object(store, "_connect", return_value=Database()),
            patch.object(store, "settle", return_value={"changed": True}) as settle,
            patch.object(store, "release", return_value=True) as release,
        ):
            self.assertEqual(store.release_stale(), 4)
        self.assertEqual({call.args[0] for call in settle.call_args_list}, {"download-success", "ai-success"})
        self.assertEqual({call.args[0] for call in release.call_args_list}, {"download-crash", "ai-failure"})
        self.assertTrue(all(call.kwargs.get("updated_before") is not None for call in release.call_args_list))


class ProductDefaultsTests(unittest.TestCase):
    def test_safe_monetization_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            configured = load_settings().monetization
        self.assertFalse(configured.enabled)
        self.assertEqual(configured.starter_credits, 100)
        self.assertEqual(configured.ai_credit_cost, 5)
        self.assertEqual(configured.daily_download_limit, 15)
        self.assertEqual(configured.ai_trials, 2)
        self.assertEqual((configured.referral_inviter_reward, configured.referral_invitee_reward), (50, 50))
        self.assertEqual(configured.referral_required_downloads, 1)
        self.assertEqual(configured.referral_monthly_cap, 5)
        self.assertEqual(configured.premium_price_stars, 149)
        self.assertEqual(configured.subscription_period_seconds, 2_592_000)
        self.assertEqual(configured.rollout_percent, 100)
        self.assertFalse(configured.premium_enabled)

    def test_rollout_is_deterministic_and_explicit_users_are_included(self):
        configured = replace(app_settings.monetization, enabled=True, rollout_percent=0, rollout_user_ids=(7,))
        with patch.object(store, "settings", SimpleNamespace(monetization=configured)):
            self.assertTrue(store.enforcement_enabled_for(7))
            self.assertFalse(store.enforcement_enabled_for(8))

    def test_account_copy_exists_in_all_supported_languages(self):
        for language in ("en", "az", "ru"):
            with self.subTest(language=language):
                self.assertNotEqual(tr(language, "credits_title"), "credits_title")
                self.assertIn("149", tr(language, "premium_offer", price=149))
                self.assertNotEqual(tr(language, "terms"), "terms")
                self.assertNotEqual(tr(language, "paysupport"), "paysupport")

    def test_schema_initialization_contains_existing_user_backfill(self):
        statements = []

        class Database:
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def execute(self, sql, params=()):
                statements.append((" ".join(sql.split()), params))
                return Cursor()

        with patch.object(store, "enabled", return_value=True), patch.object(store, "_connect", return_value=Database()):
            store.initialize()
        sql = "\n".join(statement for statement, _ in statements)
        self.assertIn("FROM bot_contacts WHERE chat_type = 'private'", sql)
        self.assertIn("starter_grant", sql)
        self.assertIn("telegram_payment_charge_id TEXT PRIMARY KEY", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS monetization_config", sql)
        settings_insert = next(
            params for statement, params in statements
            if statement.startswith("INSERT INTO monetization_config")
        )
        self.assertEqual(len(settings_insert), 18)

    def test_schema_initialization_does_not_hide_database_failures(self):
        class Database:
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def execute(self, _sql, _params=()):
                raise RuntimeError("database migration failed")

        with patch.object(store, "enabled", return_value=True), patch.object(store, "_connect", return_value=Database()):
            with self.assertRaisesRegex(RuntimeError, "Monetization database initialization failed"):
                store.initialize()


class ReferralDatabase:
    def __init__(self, *, downloads=2, qualified=0):
        self.downloads = downloads
        self.qualified = qualified
        self.rewards: list[tuple[int, int]] = []
        self.status = "pending"

    def execute(self, sql, params=()):
        normalized = " ".join(sql.split())
        if normalized.startswith("SELECT inviter_user_id"):
            return Cursor((99,))
        if normalized.startswith("SELECT COUNT(*) FROM entitlement_operations"):
            return Cursor((1,))
        if normalized.startswith("SELECT COUNT(*) FROM referrals"):
            return Cursor((self.qualified,))
        if normalized.startswith("SELECT pg_advisory_xact_lock"):
            return Cursor((None,))
        if normalized.startswith("UPDATE user_accounts SET credit_balance=credit_balance+"):
            amount, _, user_id = params
            self.rewards.append((user_id, amount))
            return Cursor((amount,))
        if normalized.startswith("INSERT INTO credit_ledger"):
            return Cursor()
        if normalized.startswith("UPDATE referrals SET status='qualified'"):
            self.status = "qualified"; return Cursor()
        if normalized.startswith("UPDATE referrals SET status='rejected'"):
            self.status = "rejected"; return Cursor()
        raise AssertionError(f"Unexpected SQL: {normalized}")


class ReferralTests(unittest.TestCase):
    def test_qualified_referral_rewards_both_sides(self):
        database = ReferralDatabase()
        with patch.object(store, "settings", fake_settings()):
            reward = store._qualify_referral(database, 7, datetime.now(timezone.utc))
        self.assertEqual(reward, {"inviter_user_id": 99, "invitee_user_id": 7, "inviter_credits": 50, "invitee_credits": 50})
        self.assertEqual(database.rewards, [(99, 50), (7, 50)])
        self.assertEqual(database.status, "qualified")

    def test_rolling_cap_blocks_additional_reward(self):
        database = ReferralDatabase(qualified=5)
        with patch.object(store, "settings", fake_settings()):
            reward = store._qualify_referral(database, 7, datetime.now(timezone.utc))
        self.assertIsNone(reward)
        self.assertEqual(database.rewards, [])
        self.assertEqual(database.status, "rejected")


class PaymentDatabase:
    def __init__(self, payload: str):
        self.digest = hashlib.sha256(payload.encode()).hexdigest()
        self.payments: dict[str, dict] = {}
        self.account_expiry = None
        self.cancelled = False
        self.order_status = "pending"

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=()):
        normalized = " ".join(sql.split())
        if normalized.startswith("SELECT 1 FROM star_payments"):
            return Cursor((1,) if params[0] in self.payments else None)
        if "FROM star_orders WHERE payload_hash=%s FOR UPDATE" in normalized:
            return Cursor((7, 149, "XTR", self.order_status) if params[0] == self.digest else None)
        if normalized.startswith("INSERT INTO star_payments"):
            charge, user_id, digest, amount, currency, expiry, recurring, first, now = params
            self.payments[charge] = {"user": user_id, "digest": digest, "amount": amount, "currency": currency, "expiry": expiry, "recurring": recurring, "first": first, "refunded": False, "created": now}
            return Cursor()
        if normalized.startswith("UPDATE star_orders"):
            self.order_status = "paid"; return Cursor()
        if normalized.startswith("UPDATE user_accounts SET subscription_expires_at=GREATEST"):
            self.account_expiry = params[1]; self.cancelled = False; return Cursor()
        if normalized.startswith("INSERT INTO entitlement_audit"):
            return Cursor()
        if normalized.startswith("UPDATE star_payments SET refunded_at"):
            _, charge, user_id = params
            payment = self.payments.get(charge)
            if not payment or payment["user"] != user_id or payment["refunded"]:
                return Cursor(None)
            payment["refunded"] = True
            return Cursor((payment["expiry"],))
        if normalized.startswith("SELECT MAX(subscription_expires_at)"):
            active = [item["expiry"] for item in self.payments.values() if not item["refunded"]]
            return Cursor((max(active) if active else None,))
        if normalized.startswith("UPDATE user_accounts SET subscription_expires_at=%s"):
            self.account_expiry = params[0]; return Cursor()
        if normalized.startswith("UPDATE user_accounts SET subscription_cancelled"):
            self.cancelled = params[0]; return Cursor()
        raise AssertionError(f"Unexpected SQL: {normalized}")


class PaymentStoreTests(unittest.TestCase):
    def test_premium_payments_are_rejected_when_launch_mode_disables_premium(self):
        with patch.object(store, "enabled", return_value=True), patch.object(store, "settings", fake_settings(premium_enabled=False)):
            with self.assertRaisesRegex(ValueError, "Premium checkout is disabled"):
                store.create_star_order(user_id=7)

    def test_payment_and_renewal_are_idempotent_and_extend_expiry(self):
        payload = "premium:7:opaque"
        database = PaymentDatabase(payload)
        first_expiry = datetime(2026, 10, 1, tzinfo=timezone.utc)
        renewal_expiry = datetime(2026, 11, 1, tzinfo=timezone.utc)
        with patch.object(store, "enabled", return_value=True), patch.object(store, "_connect", return_value=database), patch.object(store, "settings", fake_settings()):
            self.assertTrue(store.apply_star_payment(user_id=7, payload=payload, charge_id="first", amount=149, currency="XTR", expiration=first_expiry, recurring=True, first_recurring=True))
            self.assertFalse(store.apply_star_payment(user_id=7, payload=payload, charge_id="first", amount=149, currency="XTR", expiration=first_expiry, recurring=True, first_recurring=True))
            self.assertTrue(store.apply_star_payment(user_id=7, payload=payload, charge_id="renewal", amount=149, currency="XTR", expiration=renewal_expiry, recurring=True, first_recurring=False))
        self.assertEqual(database.account_expiry, renewal_expiry)
        self.assertEqual(len(database.payments), 2)

    def test_refund_is_idempotent_and_recalculates_access(self):
        payload = "premium:7:opaque"
        database = PaymentDatabase(payload)
        expiry = datetime(2026, 10, 1, tzinfo=timezone.utc)
        with patch.object(store, "enabled", return_value=True), patch.object(store, "_connect", return_value=database), patch.object(store, "settings", fake_settings()):
            store.apply_star_payment(user_id=7, payload=payload, charge_id="first", amount=149, currency="XTR", expiration=expiry, recurring=True, first_recurring=True)
            self.assertTrue(store.mark_refunded("first", 7))
            self.assertFalse(store.mark_refunded("first", 7))
        self.assertIsNone(database.account_expiry)

    def test_subscription_requires_telegram_expiration_and_recurring_marker(self):
        payload = "premium:7:opaque"
        with patch.object(store, "enabled", return_value=True), patch.object(store, "_connect", return_value=PaymentDatabase(payload)), patch.object(store, "settings", fake_settings()):
            with self.assertRaisesRegex(ValueError, "expiration"):
                store.apply_star_payment(user_id=7, payload=payload, charge_id="missing-expiry", amount=149, currency="XTR", expiration=None, recurring=True, first_recurring=True)
            with self.assertRaisesRegex(ValueError, "expiration"):
                store.apply_star_payment(user_id=7, payload=payload, charge_id="not-recurring", amount=149, currency="XTR", expiration=datetime.now(timezone.utc) + timedelta(days=30), recurring=False, first_recurring=False)

    def test_second_initial_charge_for_paid_order_is_rejected(self):
        payload = "premium:7:opaque"
        database = PaymentDatabase(payload)
        expiry = datetime.now(timezone.utc) + timedelta(days=30)
        with patch.object(store, "enabled", return_value=True), patch.object(store, "_connect", return_value=database), patch.object(store, "settings", fake_settings()):
            self.assertTrue(store.apply_star_payment(user_id=7, payload=payload, charge_id="first", amount=149, currency="XTR", expiration=expiry, recurring=True, first_recurring=True))
            with self.assertRaisesRegex(ValueError, "already paid"):
                store.apply_star_payment(user_id=7, payload=payload, charge_id="other", amount=149, currency="XTR", expiration=expiry, recurring=True, first_recurring=True)

    def test_admin_cancellation_state_is_persisted(self):
        database = PaymentDatabase("payload")
        with patch.object(store, "enabled", return_value=True), patch.object(store, "_connect", return_value=database):
            store.mark_subscription_cancelled(7)
        self.assertTrue(database.cancelled)


class PaymentHandlerTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def payment_update():
        payment = SimpleNamespace(
            invoice_payload="opaque", telegram_payment_charge_id="charge", total_amount=149,
            currency="XTR", subscription_expiration_date=datetime.now(timezone.utc) + timedelta(days=30),
            is_recurring=True, is_first_recurring=True,
        )
        message = SimpleNamespace(successful_payment=payment, reply_text=AsyncMock())
        update = SimpleNamespace(
            effective_message=message, effective_user=SimpleNamespace(id=7, language_code="en"),
            effective_chat=SimpleNamespace(id=7, type="private"),
        )
        return update, message

    async def test_precheckout_validates_user_amount_currency_and_payload(self):
        query = SimpleNamespace(
            invoice_payload="opaque", from_user=SimpleNamespace(id=7, language_code="en"),
            total_amount=149, currency="XTR", answer=AsyncMock(),
        )
        update = SimpleNamespace(pre_checkout_query=query)
        with patch.object(store, "validate_star_order", return_value=True) as validate:
            await monetization.pre_checkout(update, SimpleNamespace())
        validate.assert_called_once_with("opaque", 7, 149, "XTR")
        query.answer.assert_awaited_once_with(ok=True, error_message=None)

    async def test_duplicate_successful_payment_does_not_send_duplicate_confirmation(self):
        payment = SimpleNamespace(
            invoice_payload="opaque", telegram_payment_charge_id="charge", total_amount=149,
            currency="XTR", subscription_expiration_date=None, is_recurring=True, is_first_recurring=False,
        )
        message = SimpleNamespace(successful_payment=payment, reply_text=AsyncMock())
        update = SimpleNamespace(effective_message=message, effective_user=SimpleNamespace(id=7), effective_chat=SimpleNamespace(id=7))
        with patch.object(store, "apply_star_payment", return_value=False):
            await monetization.successful_payment(update, SimpleNamespace())
        message.reply_text.assert_not_awaited()

    async def test_transient_activation_failure_is_retried_and_confirmed(self):
        update, message = self.payment_update()
        with patch.object(store, "apply_star_payment", side_effect=[RuntimeError("database restart"), True]) as apply, patch.object(asyncio, "sleep", new=AsyncMock()) as sleep:
            await monetization.successful_payment(update, SimpleNamespace())
        self.assertEqual(apply.call_count, 2)
        sleep.assert_awaited_once()
        self.assertIn("Premium is active", message.reply_text.await_args.args[0])


class AdminEntitlementApiTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.dict(os.environ, {"ADMIN_API_TOKEN": "test-admin-token"})
        patcher.start()
        self.addCleanup(patcher.stop)
        with patch("backend.bot.api.admin.activity_store.initialize"), patch("backend.bot.api.admin.monetization_store.initialize"):
            self.client = TestClient(create_app())

    def test_users_endpoint_requires_authentication(self):
        self.assertEqual(self.client.get("/admin/users").status_code, 401)

    def test_users_endpoint_rejects_unknown_filter(self):
        response = self.client.get("/admin/users?access=owner", headers={"Authorization": "Bearer test-admin-token"})
        self.assertEqual(response.status_code, 400)

    def test_entitlement_update_accepts_optional_reason_and_validates_values(self):
        headers = {"Authorization": "Bearer test-admin-token"}
        self.assertEqual(self.client.patch("/admin/users/7", headers=headers, json={"creditAdjustment": 1, "reason": "x"}).status_code, 404)
        self.assertEqual(self.client.patch("/admin/users/7", headers=headers, json={"creditAdjustment": 100001, "reason": "manual grant"}).status_code, 400)

    def test_entitlement_update_supports_add_and_set_credit_modes_without_reason(self):
        headers = {"Authorization": "Bearer test-admin-token"}
        updated = {"telegram_user_id": 7}
        with patch.object(store, "admin_update_user", return_value=updated) as update:
            response = self.client.patch("/admin/users/7", headers=headers, json={"creditMode": "add", "creditAmount": 20})
        self.assertEqual(response.status_code, 200)
        update.assert_called_once_with(7, credit_adjustment=None, credit_mode="add", credit_amount=20, ai_trials=None, complimentary=None, reason="Admin entitlement update")

        with patch.object(store, "admin_update_user", return_value=updated) as update:
            response = self.client.patch("/admin/users/7", headers=headers, json={"creditMode": "set", "creditAmount": 30})
        self.assertEqual(response.status_code, 200)
        update.assert_called_once_with(7, credit_adjustment=None, credit_mode="set", credit_amount=30, ai_trials=None, complimentary=None, reason="Admin entitlement update")

    def test_entitlement_update_rejects_unknown_fields_zero_adjustments_and_controls(self):
        headers = {"Authorization": "Bearer test-admin-token"}
        self.assertEqual(self.client.patch("/admin/users/7", headers=headers, json={"creditAdjustment": 1, "reason": "manual grant", "admin": True}).status_code, 400)
        self.assertEqual(self.client.patch("/admin/users/7", headers=headers, json={"creditAdjustment": 0, "reason": "manual grant"}).status_code, 400)
        self.assertEqual(self.client.patch("/admin/users/7", headers=headers, json={"creditAdjustment": 1, "reason": "bad\u0000reason"}).status_code, 400)

    def test_monetization_settings_endpoint_validates_and_audits_changes(self):
        headers = {"Authorization": "Bearer test-admin-token"}
        with patch.object(store, "monetization_settings_dict", return_value={"enabled": False}) as read:
            response = self.client.get("/admin/settings/monetization", headers=headers)
        self.assertEqual(response.status_code, 200)
        read.assert_called_once()
        self.assertEqual(self.client.patch("/admin/settings/monetization", headers=headers, json={"premiumPriceStars": 0, "reason": "bad"}).status_code, 400)
        self.assertEqual(self.client.patch("/admin/settings/monetization", headers=headers, json={"unknown": 1, "reason": "bad"}).status_code, 400)
        with patch.object(store, "update_monetization_settings", return_value={"premiumPriceStars": 129}) as update:
            response = self.client.patch("/admin/settings/monetization", headers=headers, json={"premiumPriceStars": 129, "reason": "pricing test"})
        self.assertEqual(response.status_code, 200)
        update.assert_called_once_with({"premium_price_stars": 129}, reason="pricing test")

    def test_monetization_settings_accepts_missing_reason(self):
        headers = {"Authorization": "Bearer test-admin-token"}
        with patch.object(store, "update_monetization_settings", return_value={"premiumPriceStars": 129}) as update:
            response = self.client.patch("/admin/settings/monetization", headers=headers, json={"premiumPriceStars": 129})
        self.assertEqual(response.status_code, 200)
        update.assert_called_once_with({"premium_price_stars": 129}, reason="Admin settings update")

    def test_settings_endpoint_accepts_configurable_ai_credit_cost(self):
        headers = {"Authorization": "Bearer test-admin-token"}
        with patch.object(store, "update_monetization_settings", return_value={"aiCreditCost": 5}) as update:
            response = self.client.patch("/admin/settings/monetization", headers=headers, json={"aiCreditCost": 5, "reason": "set AI cost"})
        self.assertEqual(response.status_code, 200)
        update.assert_called_once_with({"ai_credit_cost": 5}, reason="set AI cost")

    def test_settings_endpoint_accepts_dynamic_daily_download_limit(self):
        headers = {"Authorization": "Bearer test-admin-token"}
        with patch.object(store, "update_monetization_settings", return_value={"dailyDownloadLimit": 15}) as update:
            response = self.client.patch("/admin/settings/monetization", headers=headers, json={"dailyDownloadLimit": 15, "reason": "set daily cap"})
        self.assertEqual(response.status_code, 200)
        update.assert_called_once_with({"daily_download_limit": 15}, reason="set daily cap")

    def test_referrals_endpoint_treats_empty_status_as_no_filter(self):
        headers = {"Authorization": "Bearer test-admin-token"}
        with patch.object(store, "admin_referrals", return_value={"referrals": [], "page": 1, "pageSize": 25, "total": 0}) as referrals:
            response = self.client.get("/admin/referrals?status=&page=1", headers=headers)
        self.assertEqual(response.status_code, 200)
        referrals.assert_called_once_with(status=None, page=1, page_size=25)


class EntitlementFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        bot.STATES.clear()
        bot.DOWNLOAD_LOCKS.clear()

    @staticmethod
    def update(callback_data: str):
        query = SimpleNamespace(
            data=callback_data, answer=AsyncMock(), edit_message_text=AsyncMock(),
            delete_message=AsyncMock(), message=SimpleNamespace(message_id=88),
        )
        update = SimpleNamespace(
            callback_query=query, effective_message=query.message,
            effective_chat=SimpleNamespace(id=70, type="private"),
            effective_user=SimpleNamespace(id=71, username="tester", full_name="Test User"),
        )
        return update, query

    async def test_insufficient_credit_keeps_link_and_back_button(self):
        update, query = self.update("")
        key = bot.save_state(update, "https://youtu.be/example", {"title": "Example"})
        query.data = f"d|720p|{key}"
        with patch.object(bot, "reserve_entitlement", return_value=None):
            await bot.button_handler(update, SimpleNamespace())
        self.assertIn(key, bot.STATES)
        text = query.edit_message_text.await_args.args[0]
        markup = query.edit_message_text.await_args.kwargs["reply_markup"]
        self.assertIn("temporarily unavailable", text)
        callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
        self.assertIn(f"m|main|{key}", callbacks)
        self.assertNotIn("acct|premium", callbacks)

    async def test_ai_reservation_is_linked_to_durable_job(self):
        update, query = self.update("")
        reservation = store.Reservation("operation", "reserved", "ai", 71)
        key = bot.save_state(update, "https://youtu.be/example", {"title": "Example"})
        query.data = f"s|{key}"
        with (
            patch.object(bot, "transcription_is_configured", return_value=True),
            patch.object(bot, "r2_is_configured", return_value=True),
            patch.object(bot, "queue_is_configured", return_value=True),
            patch.object(bot, "allow_analysis", return_value=True),
            patch.object(bot, "reserve_entitlement", return_value=reservation),
            patch.object(bot, "_run_transcription", new=AsyncMock()) as run,
        ):
            await bot.button_handler(update, SimpleNamespace())
        self.assertEqual(run.await_args.kwargs["entitlement_operation_id"], "operation")
        self.assertEqual(run.await_args.kwargs["job_type"], "summary")
        self.assertNotIn(key, bot.STATES)

    async def test_account_screen_shows_balance_trials_and_referrals(self):
        message = SimpleNamespace(reply_text=AsyncMock())
        update = SimpleNamespace(
            effective_message=message, effective_chat=SimpleNamespace(id=7, type="private"),
            effective_user=SimpleNamespace(id=7, username="tester", full_name="Test User"),
        )
        account = {
            "user_id": 7, "chat_id": 7, "credits": 8, "reserved_credits": 1,
            "ai_trials": 1, "reserved_ai_trials": 0, "premium": False,
            "complimentary": False, "subscription_expires_at": None,
            "subscription_cancelled": False,
        }
        with (
            patch.object(monetization, "ensure_update_account", return_value=account),
            patch.object(store, "referral_progress", return_value={"qualified": 2, "pending": 1}),
        ):
            await monetization.credits(update, SimpleNamespace())
        text = message.reply_text.await_args.args[0]
        self.assertIn("Credits: 7 available · 1 reserved", text)
        self.assertIn("AI transcription or summary: 5 credits", text)
        self.assertIn("2 rewarded · 1 pending", text)

    async def test_start_deep_link_attaches_referral_once(self):
        message = SimpleNamespace(reply_text=AsyncMock())
        update = SimpleNamespace(
            effective_message=message, effective_chat=SimpleNamespace(id=7, type="private"),
            effective_user=SimpleNamespace(id=7, username="tester", full_name="Test User"),
        )
        with patch.object(bot, "_record_contact"), patch.object(bot, "attach_referral", return_value="attached") as attach:
            await bot.start(update, SimpleNamespace(args=["ref_invitercode"]))
        attach.assert_called_once_with(7, "invitercode")
        self.assertIn("Referral accepted", message.reply_text.await_args_list[0].args[0])

    async def test_account_details_and_payment_are_private_chat_only(self):
        message = SimpleNamespace(reply_text=AsyncMock())
        update = SimpleNamespace(
            effective_message=message, effective_chat=SimpleNamespace(id=-1007, type="group"),
            effective_user=SimpleNamespace(id=7, username="tester", full_name="Test User"),
        )
        with patch.object(monetization, "ensure_update_account") as ensure:
            await monetization.credits(update, SimpleNamespace())
        ensure.assert_not_called()
        self.assertIn("private chat", message.reply_text.await_args.args[0])


if __name__ == "__main__":
    unittest.main()
