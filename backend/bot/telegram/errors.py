from __future__ import annotations

"""Report Telegram failures without exposing update contents or request secrets."""

import logging

from telegram.error import BadRequest, NetworkError
from telegram.ext import ContextTypes

from ..platforms.security import safe_log_error

LOG = logging.getLogger("downloader_bot.telegram")


async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Record polling outages separately from failures in user update handlers."""
    error = context.error
    if error is None:
        return
    scope = "polling" if update is None else "update"
    # BadRequest inherits NetworkError but is a rejected request, not an outage.
    if isinstance(error, NetworkError) and not isinstance(error, BadRequest):
        LOG.warning(
            "event=telegram_network_error scope=%s error_type=%s error=%s",
            scope, type(error).__name__, safe_log_error(error),
        )
        return
    LOG.error(
        "event=telegram_handler_error scope=%s error_type=%s error=%s",
        scope, type(error).__name__, safe_log_error(error),
    )
