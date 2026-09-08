from __future__ import annotations

import hmac
import os
import asyncio
import re
from typing import Any

from fastapi import Body, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from telegram import Bot
from telegram.error import TelegramError

from ..persistence import activity_store, monetization_store
from ..platforms.limits import SlidingWindowLimiter


ADMIN_REQUESTS_PER_MINUTE = min(300, max(10, int(os.getenv("ADMIN_REQUESTS_PER_MINUTE", "60"))))
MESSAGE_MAX_LENGTH = 4096
MAX_MESSAGE_RECIPIENTS = 10000
MESSAGE_SEND_DELAY_SECONDS = 0.05
_REQUEST_LIMITER = SlidingWindowLimiter(max_keys=10000)


def _authorized(authorization: str | None) -> bool:
    expected = os.getenv("ADMIN_API_TOKEN", "")
    provided = authorization.removeprefix("Bearer ").strip() if authorization else ""
    return bool(expected) and hmac.compare_digest(provided, expected)


def _client_key(request: Request) -> str:
    # Do not trust user-controlled forwarding headers for authorization. The
    # ASGI peer is the only stable identity available without a proxy module.
    return request.client.host if request.client else "unknown"


def _rate_limit(request: Request) -> None:
    if not _REQUEST_LIMITER.allow(_client_key(request), limit=ADMIN_REQUESTS_PER_MINUTE, window_seconds=60):
        raise HTTPException(status_code=429, detail="Too many requests", headers={"Retry-After": "60"})


def _message_from_payload(payload: dict[str, Any]) -> str:
    message = payload.get("message")
    if not isinstance(message, str) or not message.strip() or len(message) > MESSAGE_MAX_LENGTH:
        raise HTTPException(status_code=400, detail="Message must contain 1 to 4096 characters")
    return message


def _excluded_usernames(value: str | None) -> list[str]:
    if not value:
        return []
    usernames = []
    for candidate in value.split(","):
        normalized = candidate.strip().lstrip("@").lower()
        if not normalized:
            continue
        if not re.fullmatch(r"[a-z0-9_]{5,32}", normalized):
            raise HTTPException(status_code=400, detail="Invalid excluded username")
        if normalized not in usernames:
            usernames.append(normalized)
    if len(usernames) > 50:
        raise HTTPException(status_code=400, detail="At most 50 usernames can be excluded")
    return usernames


def _username_from_payload(payload: dict[str, Any]) -> str:
    username = payload.get("username")
    if not isinstance(username, str):
        raise HTTPException(status_code=400, detail="A Telegram username is required")
    username = username.strip()
    if not re.fullmatch(r"@?[A-Za-z0-9_]{5,32}", username):
        raise HTTPException(status_code=400, detail="Enter a valid Telegram username")
    return username if username.startswith("@") else f"@{username}"


_MONETIZATION_FIELDS = {
    "enabled": "enabled", "premiumEnabled": "premium_enabled", "starterCredits": "starter_credits", "aiCreditCost": "ai_credit_cost", "dailyDownloadLimit": "daily_download_limit", "aiTrials": "ai_trials",
    "referralInviterReward": "referral_inviter_reward", "referralInviteeReward": "referral_invitee_reward",
    "referralRequiredDownloads": "referral_required_downloads", "referralMonthlyCap": "referral_monthly_cap",
    "premiumPriceStars": "premium_price_stars", "staleReservationSeconds": "stale_reservation_seconds",
    "costAlertFileMb": "cost_alert_file_mb", "rolloutPercent": "rollout_percent",
    "rolloutUserIds": "rollout_user_ids",
}


def _monetization_patch(payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
    unknown = set(payload) - {*_MONETIZATION_FIELDS, "reason"}
    if unknown:
        raise HTTPException(status_code=400, detail="Unknown monetization setting")
    reason = payload.get("reason")
    if not isinstance(reason, str) or not 3 <= len(reason.strip()) <= 500:
        raise HTTPException(status_code=400, detail="A reason of 3 to 500 characters is required")
    changes = {}
    for public_name, internal_name in _MONETIZATION_FIELDS.items():
        if public_name in payload:
            changes[internal_name] = payload[public_name]
    if not changes:
        raise HTTPException(status_code=400, detail="No monetization setting supplied")
    ranges = {
        "starterCredits": (0, 1000), "aiCreditCost": (0, 1000), "dailyDownloadLimit": (1, 500), "aiTrials": (0, 100), "referralInviterReward": (0, 1000),
        "referralInviteeReward": (0, 1000), "referralRequiredDownloads": (1, 100),
        "referralMonthlyCap": (0, 100), "premiumPriceStars": (1, 100000),
        "staleReservationSeconds": (300, 86400), "costAlertFileMb": (1, 4096),
        "rolloutPercent": (0, 100),
    }
    for boolean_name in ("enabled", "premiumEnabled"):
        if boolean_name in payload and type(payload[boolean_name]) is not bool:
            raise HTTPException(status_code=400, detail=f"{boolean_name} must be a boolean")
    for name, (minimum, maximum) in ranges.items():
        if name in payload and (type(payload[name]) is not int or not minimum <= payload[name] <= maximum):
            raise HTTPException(status_code=400, detail=f"{name} is outside its safe range")
    if "rolloutUserIds" in payload and (not isinstance(payload["rolloutUserIds"], list) or len(payload["rolloutUserIds"]) > 1000 or any(type(value) is not int or not 0 < value <= 9_223_372_036_854_775_807 for value in payload["rolloutUserIds"])):
        raise HTTPException(status_code=400, detail="rolloutUserIds must contain at most 1000 valid Telegram IDs")
    return changes, reason.strip()


async def _send_to_chats(chat_ids: list[int], message: str) -> tuple[int, int]:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise HTTPException(status_code=503, detail="Bot messaging is not configured")
    sent = 0
    failed = 0
    async with Bot(token=token) as bot:
        for chat_id in chat_ids:
            try:
                await bot.send_message(chat_id=chat_id, text=message)
                activity_store.record_message(chat_id=chat_id, username=None, display_name=None, direction="outbound", text=message)
                sent += 1
            except TelegramError as exc:
                activity_store.record_message(chat_id=chat_id, username=None, display_name=None, direction="outbound", text=message, delivered=False, error=str(exc))
                failed += 1
            await asyncio.sleep(MESSAGE_SEND_DELAY_SECONDS)
    return sent, failed


async def _send_direct_message(chat_id: int, message: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise HTTPException(status_code=503, detail="Bot messaging is not configured")
    async with Bot(token=token) as bot:
        try:
            sent_message = await bot.send_message(chat_id=chat_id, text=message)
        except TelegramError as exc:
            activity_store.record_message(chat_id=chat_id, username=None, display_name=None, direction="outbound", text=message, delivered=False, error=str(exc))
            return False
    activity_store.record_message(
        chat_id=chat_id,
        username=None,
        display_name=None,
        direction="outbound",
        text=message,
        telegram_message_id=getattr(sent_message, "message_id", None),
    )
    return True


def create_app() -> FastAPI:
    activity_store.initialize()
    monetization_store.initialize()
    app = FastAPI(title="Downloader Admin API", docs_url=None, redoc_url=None)

    @app.get("/health")
    async def health(request: Request) -> dict[str, str]:
        _rate_limit(request)
        return {"status": "ok"}

    @app.get("/admin/activity")
    async def activity(request: Request, authorization: str | None = Header(default=None), q: str | None = Query(default=None), platform: str | None = Query(default=None), status: str | None = Query(default=None), action: str | None = Query(default=None), exclude_users: str | None = Query(default=None, alias="excludeUsers", max_length=1700), page: int = Query(default=1, ge=1), page_size: int = Query(default=25, alias="pageSize", ge=1, le=100)) -> JSONResponse:
        _rate_limit(request)
        if not _authorized(authorization):
            raise HTTPException(status_code=401, detail="Unauthorized")
        if platform and platform not in {"youtube", "instagram", "facebook", "tiktok", "x", "linkedin"}:
            raise HTTPException(status_code=400, detail="Invalid platform filter")
        if status and status not in {"started", "completed", "failed", "cancelled"}:
            raise HTTPException(status_code=400, detail="Invalid status filter")
        if action and action not in {"download", "transcript", "summary", "transcribe", "summarize"}:
            raise HTTPException(status_code=400, detail="Invalid action filter")
        q = q.strip()[:100] if q else None
        excluded_usernames = _excluded_usernames(exclude_users)
        try:
            result = activity_store.query_events(q=q, platform=platform, status=status, action=action, excluded_usernames=excluded_usernames, page=page, page_size=page_size)
        except Exception:
            raise HTTPException(status_code=503, detail="Activity database unavailable") from None
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    @app.get("/admin/users")
    async def users(request: Request, authorization: str | None = Header(default=None), q: str | None = Query(default=None, max_length=100), access: str | None = Query(default=None), page: int = Query(default=1, ge=1), page_size: int = Query(default=25, alias="pageSize", ge=1, le=100)) -> JSONResponse:
        _rate_limit(request)
        if not _authorized(authorization):
            raise HTTPException(status_code=401, detail="Unauthorized")
        if access not in {None, "free", "subscribed", "complimentary", "low_credit", "ai_exhausted"}:
            raise HTTPException(status_code=400, detail="Invalid access filter")
        try:
            result = await asyncio.to_thread(
                monetization_store.admin_query_users,
                q=q.strip() if q else None, access=access, page=page, page_size=page_size,
            )
        except Exception:
            raise HTTPException(status_code=503, detail="Account database unavailable") from None
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    @app.get("/admin/usage")
    async def usage(request: Request, authorization: str | None = Header(default=None), days: int = Query(default=30, ge=1, le=365)) -> JSONResponse:
        _rate_limit(request)
        if not _authorized(authorization): raise HTTPException(status_code=401, detail="Unauthorized")
        try: result = await asyncio.to_thread(monetization_store.admin_usage, days)
        except Exception: raise HTTPException(status_code=503, detail="Account database unavailable") from None
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    @app.get("/admin/credits")
    async def credits(request: Request, authorization: str | None = Header(default=None), q: str | None = Query(default=None, max_length=100), page: int = Query(default=1, ge=1), page_size: int = Query(default=25, alias="pageSize", ge=1, le=100)) -> JSONResponse:
        _rate_limit(request)
        if not _authorized(authorization): raise HTTPException(status_code=401, detail="Unauthorized")
        try: result = await asyncio.to_thread(monetization_store.admin_credit_overview, q=q.strip() if q else None, page=page, page_size=page_size)
        except Exception: raise HTTPException(status_code=503, detail="Account database unavailable") from None
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    @app.get("/admin/referrals")
    async def referrals(request: Request, authorization: str | None = Header(default=None), status: str | None = Query(default=None), page: int = Query(default=1, ge=1), page_size: int = Query(default=25, alias="pageSize", ge=1, le=100)) -> JSONResponse:
        _rate_limit(request)
        if not _authorized(authorization): raise HTTPException(status_code=401, detail="Unauthorized")
        status = status or None
        if status not in {None, "pending", "qualified", "rejected"}: raise HTTPException(status_code=400, detail="Invalid referral status")
        try: result = await asyncio.to_thread(monetization_store.admin_referrals, status=status, page=page, page_size=page_size)
        except Exception: raise HTTPException(status_code=503, detail="Account database unavailable") from None
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    @app.get("/admin/transactions")
    async def transactions(request: Request, authorization: str | None = Header(default=None), q: str | None = Query(default=None, max_length=100), page: int = Query(default=1, ge=1), page_size: int = Query(default=25, alias="pageSize", ge=1, le=100)) -> JSONResponse:
        _rate_limit(request)
        if not _authorized(authorization): raise HTTPException(status_code=401, detail="Unauthorized")
        try: result = await asyncio.to_thread(monetization_store.admin_transactions, q=q.strip() if q else None, page=page, page_size=page_size)
        except Exception: raise HTTPException(status_code=503, detail="Account database unavailable") from None
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    @app.get("/admin/settings/monetization")
    async def monetization_settings(request: Request, authorization: str | None = Header(default=None)) -> JSONResponse:
        _rate_limit(request)
        if not _authorized(authorization):
            raise HTTPException(status_code=401, detail="Unauthorized")
        try:
            result = await asyncio.to_thread(monetization_store.monetization_settings_dict)
        except Exception:
            raise HTTPException(status_code=503, detail="Settings database unavailable") from None
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    @app.patch("/admin/settings/monetization")
    async def update_monetization_settings(request: Request, payload: dict[str, Any] = Body(...), authorization: str | None = Header(default=None)) -> JSONResponse:
        _rate_limit(request)
        if not _authorized(authorization):
            raise HTTPException(status_code=401, detail="Unauthorized")
        try:
            changes, reason = _monetization_patch(payload)
            result = await asyncio.to_thread(monetization_store.update_monetization_settings, changes, reason=reason)
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        except Exception:
            raise HTTPException(status_code=503, detail="Settings database unavailable") from None
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    @app.get("/admin/settings/monetization/history")
    async def monetization_settings_history(request: Request, authorization: str | None = Header(default=None), limit: int = Query(default=100, ge=1, le=200)) -> JSONResponse:
        _rate_limit(request)
        if not _authorized(authorization):
            raise HTTPException(status_code=401, detail="Unauthorized")
        try:
            history = await asyncio.to_thread(monetization_store.monetization_settings_history, limit)
        except Exception:
            raise HTTPException(status_code=503, detail="Settings database unavailable") from None
        return JSONResponse({"history": history}, headers={"Cache-Control": "no-store"})

    @app.patch("/admin/users/{user_id}")
    async def update_user(user_id: int, request: Request, payload: dict[str, Any] = Body(...), authorization: str | None = Header(default=None)) -> JSONResponse:
        _rate_limit(request)
        if not _authorized(authorization):
            raise HTTPException(status_code=401, detail="Unauthorized")
        if user_id <= 0 or user_id > 9_223_372_036_854_775_807:
            raise HTTPException(status_code=400, detail="Invalid Telegram user ID")
        unknown = set(payload) - {"creditAdjustment", "aiTrials", "complimentary", "reason"}
        if unknown:
            raise HTTPException(status_code=400, detail="Unknown entitlement field")
        reason = payload.get("reason")
        if (not isinstance(reason, str) or not 3 <= len(reason.strip()) <= 500
                or any(ord(character) < 32 and character not in "\t\n\r" for character in reason)):
            raise HTTPException(status_code=400, detail="A reason of 3 to 500 characters is required")
        adjustment = payload.get("creditAdjustment")
        ai_trials = payload.get("aiTrials")
        complimentary = payload.get("complimentary")
        if adjustment is not None and (type(adjustment) is not int or not -100_000 <= adjustment <= 100_000):
            raise HTTPException(status_code=400, detail="Credit adjustment must be an integer from -100000 to 100000")
        if adjustment == 0:
            raise HTTPException(status_code=400, detail="Credit adjustment cannot be zero")
        if ai_trials is not None and (type(ai_trials) is not int or not 0 <= ai_trials <= 100):
            raise HTTPException(status_code=400, detail="AI trials must be an integer from 0 to 100")
        if complimentary is not None and type(complimentary) is not bool:
            raise HTTPException(status_code=400, detail="Complimentary access must be true or false")
        if adjustment is None and ai_trials is None and complimentary is None:
            raise HTTPException(status_code=400, detail="No entitlement change supplied")
        try:
            updated = await asyncio.to_thread(
                monetization_store.admin_update_user, user_id,
                credit_adjustment=adjustment, ai_trials=ai_trials,
                complimentary=complimentary, reason=reason.strip(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        except Exception:
            raise HTTPException(status_code=503, detail="Account database unavailable") from None
        if not updated:
            raise HTTPException(status_code=404, detail="User not found")
        return JSONResponse({"user": updated}, headers={"Cache-Control": "no-store"})

    @app.get("/admin/users/{user_id}/history")
    async def user_history(user_id: int, request: Request, authorization: str | None = Header(default=None), limit: int = Query(default=100, ge=1, le=200)) -> JSONResponse:
        _rate_limit(request)
        if not _authorized(authorization):
            raise HTTPException(status_code=401, detail="Unauthorized")
        if user_id <= 0 or user_id > 9_223_372_036_854_775_807:
            raise HTTPException(status_code=400, detail="Invalid Telegram user ID")
        try:
            history = await asyncio.to_thread(monetization_store.admin_history, user_id, limit)
        except Exception:
            raise HTTPException(status_code=503, detail="Account database unavailable") from None
        return JSONResponse({"history": history}, headers={"Cache-Control": "no-store"})

    @app.delete("/admin/activity")
    async def delete_activity(request: Request, payload: dict[str, Any] = Body(...), authorization: str | None = Header(default=None)) -> JSONResponse:
        _rate_limit(request)
        if not _authorized(authorization):
            raise HTTPException(status_code=401, detail="Unauthorized")
        event_ids = payload.get("ids")
        if not isinstance(event_ids, list) or not event_ids or len(event_ids) > 100 or not all(isinstance(event_id, str) for event_id in event_ids):
            raise HTTPException(status_code=400, detail="Provide between 1 and 100 event IDs")
        try:
            deleted = activity_store.delete_events(event_ids)
        except Exception:
            raise HTTPException(status_code=503, detail="Activity database unavailable") from None
        return JSONResponse({"deleted": deleted}, headers={"Cache-Control": "no-store"})

    @app.post("/admin/broadcast")
    async def broadcast(request: Request, payload: dict[str, Any] = Body(...), authorization: str | None = Header(default=None)) -> JSONResponse:
        _rate_limit(request)
        if not _authorized(authorization):
            raise HTTPException(status_code=401, detail="Unauthorized")
        message = _message_from_payload(payload)
        chat_ids = activity_store.recipient_chat_ids()
        if len(chat_ids) > MAX_MESSAGE_RECIPIENTS:
            raise HTTPException(status_code=503, detail="Recipient list exceeds the safe broadcast limit")
        sent, failed = await _send_to_chats(chat_ids, message)
        return JSONResponse({"targeted": len(chat_ids), "sent": sent, "failed": failed}, headers={"Cache-Control": "no-store"})

    @app.post("/admin/message")
    async def message(request: Request, payload: dict[str, Any] = Body(...), authorization: str | None = Header(default=None)) -> JSONResponse:
        _rate_limit(request)
        if not _authorized(authorization):
            raise HTTPException(status_code=401, detail="Unauthorized")
        text = _message_from_payload(payload)
        username = _username_from_payload(payload)
        chat_ids = activity_store.recipient_chat_ids(username)
        if not chat_ids:
            raise HTTPException(status_code=404, detail="No private chat found for that username")
        sent, failed = await _send_to_chats(chat_ids[:MAX_MESSAGE_RECIPIENTS], text)
        return JSONResponse({"username": username, "targeted": len(chat_ids), "sent": sent, "failed": failed}, headers={"Cache-Control": "no-store"})

    @app.get("/admin/feedback")
    async def feedback(request: Request, authorization: str | None = Header(default=None), q: str | None = Query(default=None), status: str | None = Query(default=None), page: int = Query(default=1, ge=1), page_size: int = Query(default=25, alias="pageSize", ge=1, le=100)) -> JSONResponse:
        _rate_limit(request)
        if not _authorized(authorization):
            raise HTTPException(status_code=401, detail="Unauthorized")
        try:
            result = activity_store.query_feedback(status=status, q=q, page=page, page_size=page_size)
        except Exception:
            raise HTTPException(status_code=503, detail="Feedback database unavailable") from None
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    @app.patch("/admin/feedback/{feedback_id}")
    async def update_feedback(feedback_id: str, request: Request, payload: dict[str, Any] = Body(...), authorization: str | None = Header(default=None)) -> JSONResponse:
        _rate_limit(request)
        if not _authorized(authorization):
            raise HTTPException(status_code=401, detail="Unauthorized")
        status = payload.get("status")
        if status not in {"new", "reviewed"}:
            raise HTTPException(status_code=400, detail="Status must be new or reviewed")
        try:
            updated = activity_store.update_feedback_status(feedback_id, status)
        except Exception:
            raise HTTPException(status_code=503, detail="Feedback database unavailable") from None
        if not updated:
            raise HTTPException(status_code=404, detail="Feedback not found")
        return JSONResponse({"updated": True}, headers={"Cache-Control": "no-store"})

    @app.delete("/admin/feedback/{feedback_id}")
    async def remove_feedback(feedback_id: str, request: Request, authorization: str | None = Header(default=None)) -> JSONResponse:
        _rate_limit(request)
        if not _authorized(authorization):
            raise HTTPException(status_code=401, detail="Unauthorized")
        try:
            deleted = activity_store.delete_feedback(feedback_id)
        except Exception:
            raise HTTPException(status_code=503, detail="Feedback database unavailable") from None
        if not deleted:
            raise HTTPException(status_code=404, detail="Feedback not found")
        return JSONResponse({"deleted": True}, headers={"Cache-Control": "no-store"})

    @app.get("/admin/conversations")
    async def conversations(request: Request, authorization: str | None = Header(default=None), q: str | None = Query(default=None), limit: int = Query(default=50, ge=1, le=100)) -> JSONResponse:
        _rate_limit(request)
        if not _authorized(authorization):
            raise HTTPException(status_code=401, detail="Unauthorized")
        try:
            result = activity_store.query_conversations(q=q, limit=limit)
        except Exception:
            raise HTTPException(status_code=503, detail="Chat database unavailable") from None
        return JSONResponse({"conversations": result}, headers={"Cache-Control": "no-store"})

    @app.get("/admin/conversations/{chat_id}/messages")
    async def conversation_messages(chat_id: int, request: Request, authorization: str | None = Header(default=None), limit: int = Query(default=100, ge=1, le=200)) -> JSONResponse:
        _rate_limit(request)
        if not _authorized(authorization):
            raise HTTPException(status_code=401, detail="Unauthorized")
        try:
            result = activity_store.query_messages(chat_id, limit=limit)
        except Exception:
            raise HTTPException(status_code=503, detail="Chat database unavailable") from None
        return JSONResponse({"messages": result}, headers={"Cache-Control": "no-store"})

    @app.post("/admin/conversations/{chat_id}/read")
    async def mark_read(chat_id: int, request: Request, authorization: str | None = Header(default=None)) -> JSONResponse:
        _rate_limit(request)
        if not _authorized(authorization):
            raise HTTPException(status_code=401, detail="Unauthorized")
        activity_store.mark_conversation_read(chat_id)
        return JSONResponse({"ok": True}, headers={"Cache-Control": "no-store"})

    @app.delete("/admin/conversations/{chat_id}")
    async def remove_conversation(chat_id: int, request: Request, authorization: str | None = Header(default=None)) -> JSONResponse:
        _rate_limit(request)
        if not _authorized(authorization):
            raise HTTPException(status_code=401, detail="Unauthorized")
        try:
            hidden = activity_store.hide_conversation(chat_id)
        except Exception:
            raise HTTPException(status_code=503, detail="Chat database unavailable") from None
        if not hidden:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return JSONResponse({"removed": True}, headers={"Cache-Control": "no-store"})

    @app.post("/admin/conversations/{chat_id}/messages")
    async def reply_to_conversation(chat_id: int, request: Request, payload: dict[str, Any] = Body(...), authorization: str | None = Header(default=None)) -> JSONResponse:
        _rate_limit(request)
        if not _authorized(authorization):
            raise HTTPException(status_code=401, detail="Unauthorized")
        text = _message_from_payload(payload)
        try:
            sent = await _send_direct_message(chat_id, text)
        except HTTPException:
            raise
        if not sent:
            raise HTTPException(status_code=502, detail="Telegram could not deliver the message")
        return JSONResponse({"sent": True}, headers={"Cache-Control": "no-store"})

    return app
