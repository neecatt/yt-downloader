"""Account, referral, and Telegram Stars user flows."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, Update
from telegram.ext import ContextTypes
from telegram.ext.filters import MessageFilter

from ..persistence import monetization_store
from .commands import _app


def ensure_update_account(update: Any) -> dict[str, Any] | None:
    user, chat = update.effective_user, update.effective_chat
    if not user or not chat:
        return None
    return monetization_store.ensure_account(
        user_id=user.id, chat_id=chat.id if getattr(chat, "type", None) == "private" else None,
        username=f"@{user.username}" if getattr(user, "username", None) else None,
        display_name=getattr(user, "full_name", None),
    )


def access_keyboard(language: str, state_key: str | None = None) -> InlineKeyboardMarkup:
    app = _app()
    row = [InlineKeyboardButton(app.tr(language, "invite_button"), callback_data="acct|invite")]
    if app.monetization_settings().enabled and app.monetization_settings().premium_enabled:
        row.append(InlineKeyboardButton(app.tr(language, "upgrade_button"), callback_data="acct|premium"))
    rows = [row]
    if state_key:
        rows.append([InlineKeyboardButton(app.tr(language, "back_to_formats"), callback_data=f"m|main|{state_key}")])
    return InlineKeyboardMarkup(rows)


def _date(value: Any) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d") if value else "—"


def account_text(account: dict[str, Any], progress: dict[str, Any], language: str) -> str:
    app = _app()
    unlimited = account["premium"]
    access = (app.tr(language, "complimentary_active") if account["complimentary"] else
              app.tr(language, "premium_active", date=_date(account["subscription_expires_at"])) if account["premium"] else
              app.tr(language, "free_account"))
    credit_line = app.tr(language, "credits_unlimited") if unlimited else app.tr(language, "credits_balance", available=max(0, account["credits"] - account["reserved_credits"]), reserved=account["reserved_credits"])
    ai_line = app.tr(language, "ai_unlimited") if unlimited else app.tr(language, "ai_cost", cost=app.monetization_settings().ai_credit_cost)
    return "\n".join((app.tr(language, "credits_title"), "", access, credit_line, ai_line,
                      app.tr(language, "referral_progress", qualified=progress["qualified"], pending=progress["pending"])))


async def credits(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    app = _app(); language = app.language_for_update(update)
    if getattr(update.effective_chat, "type", None) != "private":
        await update.effective_message.reply_text(app.tr(language, "account_private_only")); return
    account = ensure_update_account(update)
    if not account:
        await update.effective_message.reply_text(app.tr(language, "account_unavailable")); return
    progress = monetization_store.referral_progress(account["user_id"])
    rows = list(access_keyboard(language).inline_keyboard)
    expiry = account["subscription_expires_at"]
    if expiry and expiry > datetime.now(timezone.utc) and not account["subscription_cancelled"]:
        rows.append([InlineKeyboardButton(app.tr(language, "cancel_renewal_button"), callback_data="acct|cancel")])
    await update.effective_message.reply_text(account_text(account, progress, language), reply_markup=InlineKeyboardMarkup(rows))


async def invite(update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit: bool = False) -> None:
    app = _app(); language = app.language_for_update(update)
    config = app.monetization_settings()
    if getattr(update.effective_chat, "type", None) != "private":
        text = app.tr(language, "account_private_only")
        if edit and update.callback_query: await update.callback_query.edit_message_text(text)
        else: await update.effective_message.reply_text(text)
        return
    account = ensure_update_account(update)
    if not account:
        text = app.tr(language, "account_unavailable")
    else:
        username = getattr(context.bot, "username", None) or (await context.bot.get_me()).username
        text = app.tr(
            language, "invite_text", url=f"https://t.me/{username}?start=ref_{account['referral_code']}",
            required=config.referral_required_downloads,
            inviter_reward=config.referral_inviter_reward,
            invitee_reward=config.referral_invitee_reward,
            cap=config.referral_monthly_cap,
        )
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=access_keyboard(language))
    else:
        await update.effective_message.reply_text(text, reply_markup=access_keyboard(language))


async def premium(update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit: bool = False) -> None:
    app = _app(); language = app.language_for_update(update)
    config = app.monetization_settings()
    if getattr(update.effective_chat, "type", None) != "private":
        text = app.tr(language, "account_private_only")
        if edit and update.callback_query: await update.callback_query.edit_message_text(text)
        else: await update.effective_message.reply_text(text)
        return
    account = ensure_update_account(update)
    if account and account["premium"]:
        text, markup = app.tr(language, "premium_already_active"), None
    else:
        text = (f"{app.tr(language, 'premium_offer', price=config.premium_price_stars)}\n\n{app.tr(language, 'terms')}" if config.enabled and config.premium_enabled
                else app.tr(language, "premium_unavailable"))
        markup = InlineKeyboardMarkup([[InlineKeyboardButton(app.tr(language, "buy_premium"), callback_data="acct|buy")]]) if config.enabled and config.premium_enabled else None
    if edit and update.callback_query: await update.callback_query.edit_message_text(text, reply_markup=markup)
    else: await update.effective_message.reply_text(text, reply_markup=markup)


async def terms(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    app = _app(); await update.effective_message.reply_text(app.tr(app.language_for_update(update), "terms"))


async def paysupport(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    app = _app(); await update.effective_message.reply_text(app.tr(app.language_for_update(update), "paysupport"))


async def handle_callback(update: Any, context: Any, action: str) -> None:
    app = _app(); query = update.callback_query; language = app.language_for_update(update)
    if getattr(update.effective_chat, "type", None) != "private":
        await query.edit_message_text(app.tr(language, "account_private_only")); return
    if action == "invite": await invite(update, context, edit=True); return
    if action == "premium": await premium(update, context, edit=True); return
    account = ensure_update_account(update)
    if not account:
        await query.edit_message_text(app.tr(language, "account_unavailable")); return
    if action == "buy":
        config = app.monetization_settings()
        if not config.enabled or not config.premium_enabled:
            await query.edit_message_text(app.tr(language, "premium_unavailable")); return
        if account["premium"]:
            await query.edit_message_text(app.tr(language, "premium_already_active")); return
        try:
            payload = await asyncio.to_thread(monetization_store.create_star_order, account["user_id"])
            await context.bot.send_invoice(
                chat_id=account["user_id"], title=app.tr(language, "premium_invoice_title"),
                description=app.tr(language, "premium_invoice_description"),
                payload=payload, currency="XTR", prices=[LabeledPrice(app.tr(language, "premium_invoice_price"), config.premium_price_stars)],
                api_kwargs={"subscription_period": config.subscription_period_seconds},
            )
        except ValueError:
            await query.edit_message_text(app.tr(language, "premium_already_active"))
        except Exception:
            app.LOG.exception("event=premium_invoice_failed user_id=%s", account["user_id"])
            await query.edit_message_text(app.tr(language, "account_unavailable"))
        return
    if action == "cancel":
        charge_id = await asyncio.to_thread(monetization_store.latest_active_charge, account["user_id"])
        if not charge_id:
            await query.edit_message_text(app.tr(language, "renewal_cancel_failed")); return
        try:
            await context.bot.edit_user_star_subscription(user_id=account["user_id"], telegram_payment_charge_id=charge_id, is_canceled=True)
            await asyncio.to_thread(monetization_store.mark_subscription_cancelled, account["user_id"])
            await query.edit_message_text(app.tr(language, "renewal_cancelled", date=_date(account["subscription_expires_at"])))
        except Exception:
            app.LOG.exception("event=subscription_cancel_failed user_id=%s", account["user_id"])
            await query.edit_message_text(app.tr(language, "renewal_cancel_failed"))
        return
    if action not in {"buy", "cancel"}:
        await query.edit_message_text(app.tr(language, "invalid_button"))


async def pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.pre_checkout_query
    try:
        valid = await asyncio.wait_for(asyncio.to_thread(
            monetization_store.validate_star_order,
            query.invoice_payload, query.from_user.id, query.total_amount, query.currency,
        ), timeout=7)
    except Exception:
        _app().LOG.warning("event=precheckout_validation_failed user_id=%s", query.from_user.id, exc_info=True)
        valid = False
    await query.answer(ok=valid, error_message=None if valid else _app().tr(query.from_user.language_code, "premium_payment_invalid"))


async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    app = _app(); payment = update.effective_message.successful_payment; user = update.effective_user
    if not payment or not user: return
    had_error = False
    for attempt in range(3):
        try:
            changed = await asyncio.to_thread(
                monetization_store.apply_star_payment,
                user_id=user.id, payload=payment.invoice_payload, charge_id=payment.telegram_payment_charge_id,
                amount=payment.total_amount, currency=payment.currency,
                expiration=payment.subscription_expiration_date, recurring=bool(payment.is_recurring),
                first_recurring=bool(payment.is_first_recurring),
            )
            if changed:
                await update.effective_message.reply_text(app.tr(app.language_for_update(update), "premium_paid"))
            elif had_error:
                account = await asyncio.to_thread(monetization_store.get_account, user.id)
                if account and account["premium"]:
                    await update.effective_message.reply_text(app.tr(app.language_for_update(update), "premium_paid"))
            return
        except Exception:
            had_error = True
            app.LOG.warning("event=payment_activation_retry user_id=%s attempt=%s", user.id, attempt + 1, exc_info=True)
            if attempt < 2:
                await asyncio.sleep(0.25 * (2 ** attempt))
    app.LOG.error("event=payment_activation_failed user_id=%s", user.id)
    await update.effective_message.reply_text(app.tr(app.language_for_update(update), "paysupport"))


class RefundedPaymentFilter(MessageFilter):
    def filter(self, message: Any) -> bool:
        return getattr(message, "refunded_payment", None) is not None


REFUNDED_PAYMENT = RefundedPaymentFilter(name="RefundedPayment")


async def refunded_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    payment, user = getattr(update.effective_message, "refunded_payment", None), update.effective_user
    if payment and user:
        await asyncio.to_thread(monetization_store.mark_refunded, payment.telegram_payment_charge_id, user.id)
