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


def format_choice(key: str, language: str) -> InlineKeyboardMarkup:
    """Keep the most common actions one tap away; group advanced formats."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(tr(language, "recommended_720"), callback_data=f"d|720p|{key}"),
            InlineKeyboardButton(tr(language, "mp3_192"), callback_data=f"d|mp3_192|{key}"),
        ],
        [
            InlineKeyboardButton(tr(language, "transcribe"), callback_data=f"t|{key}"),
            InlineKeyboardButton(tr(language, "summarize"), callback_data=f"s|{key}"),
        ],
        [
            InlineKeyboardButton(tr(language, "video_options"), callback_data=f"m|video|{key}"),
            InlineKeyboardButton(tr(language, "audio_options"), callback_data=f"m|audio|{key}"),
        ],
    ])


def video_formats(key: str, language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(tr(language, "fast_360"), callback_data=f"d|360p|{key}"), InlineKeyboardButton(tr(language, "quality_480"), callback_data=f"d|480p|{key}")],
        [InlineKeyboardButton(tr(language, "quality_720"), callback_data=f"d|720p|{key}"), InlineKeyboardButton(tr(language, "quality_1080"), callback_data=f"d|1080p|{key}")],
        [InlineKeyboardButton(tr(language, "best"), callback_data=f"d|best|{key}")],
        [InlineKeyboardButton(tr(language, "back_to_formats"), callback_data=f"m|main|{key}")],
    ])


def audio_formats(key: str, language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(tr(language, "mp3_128"), callback_data=f"d|mp3_128|{key}"), InlineKeyboardButton(tr(language, "mp3_192"), callback_data=f"d|mp3_192|{key}")],
        [InlineKeyboardButton(tr(language, "mp3_320"), callback_data=f"d|mp3_320|{key}")],
        [InlineKeyboardButton(tr(language, "back_to_formats"), callback_data=f"m|main|{key}")],
    ])


def delivery_choice(key: str, language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(tr(language, "choice_telegram"), callback_data=f"p|telegram|{key}")],
        [InlineKeyboardButton(tr(language, "choice_link"), callback_data=f"p|r2|{key}")],
    ])
