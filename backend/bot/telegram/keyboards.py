"""Reusable Telegram inline keyboard builders."""

from __future__ import annotations

from collections.abc import Callable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ..i18n import language_keyboard, tr


def start(language: str, support_builder: Callable[[str], InlineKeyboardMarkup | None]) -> InlineKeyboardMarkup:
    rows = list(language_keyboard().inline_keyboard)
    support = support_builder(language)
    if support:
        rows.extend(support.inline_keyboard)
    return InlineKeyboardMarkup(rows)


def transcription_fallback(key: str, language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(tr(language, "transcribe"), callback_data=f"t|{key}")]])


def delivery_choice(key: str, language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(tr(language, "choice_telegram"), callback_data=f"p|telegram|{key}")],
        [InlineKeyboardButton(tr(language, "choice_link"), callback_data=f"p|r2|{key}")],
    ])
