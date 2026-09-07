"""Safe, readable Telegram presentation for generated video summaries."""

from __future__ import annotations

import html
import re
import textwrap
from typing import Any

from telegram.constants import ParseMode


_BOLD = re.compile(r"\*\*(.+?)\*\*")
_META_TRANSCRIPT = re.compile(r"\b(the|this) transcript\b", re.IGNORECASE)
_HEADINGS = {
    "overview": "🎬 Video overview",
    "video overview": "🎬 Video overview",
    "key points": "🔑 Key takeaways",
    "key takeaways": "🔑 Key takeaways",
}
_OMITTED_HEADINGS = {"why it matters", "action items", "next steps"}


def _heading(line: str) -> str:
    return line.strip().lstrip("#").strip().strip("*").strip().rstrip(":").strip().lower()


def _requested_sections_only(text: str) -> str:
    """Drop unwanted generated sections while preserving legacy unstructured text."""
    lines = text.split("\n")
    has_known_heading = any(_heading(line) in {*_HEADINGS, *_OMITTED_HEADINGS} for line in lines)
    if not has_known_heading:
        return text
    kept: list[str] = []
    include = True
    for line in lines:
        heading = _heading(line)
        if heading in _HEADINGS:
            include = True
        elif heading in _OMITTED_HEADINGS:
            include = False
            continue
        if include:
            kept.append(line)
    return "\n".join(kept).strip()


def _video_wording(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        prefix = match.group(1)
        replacement = f"{prefix} video"
        return replacement.capitalize() if match.group(0)[0].isupper() else replacement

    return _META_TRANSCRIPT.sub(replace, text)


def _inline_html(text: str) -> str:
    parts: list[str] = []
    cursor = 0
    for match in _BOLD.finditer(text):
        parts.append(html.escape(text[cursor:match.start()]))
        parts.append(f"<b>{html.escape(match.group(1))}</b>")
        cursor = match.end()
    parts.append(html.escape(text[cursor:]))
    return "".join(parts)


def _format_line(line: str) -> str:
    stripped = line.strip()
    if not stripped:
        return ""
    heading = _heading(stripped)
    if heading in _HEADINGS:
        return f"<b>{html.escape(_HEADINGS[heading])}</b>"
    if stripped.startswith(("- ", "* ")):
        return f"• {_inline_html(stripped[2:].strip())}"
    return _inline_html(stripped)


def telegram_summary_chunks(summary: str, *, max_length: int = 4000) -> list[str]:
    """Convert limited Markdown to escaped Telegram HTML without broken tags."""
    max_length = max(256, min(4000, max_length))
    normalized = _requested_sections_only(_video_wording(summary).replace("\r\n", "\n").replace("\r", "\n").strip())
    if not normalized:
        return []
    rendered_lines: list[str] = []
    for raw_line in normalized.split("\n"):
        rendered = _format_line(raw_line)
        if len(rendered) <= max_length:
            rendered_lines.append(rendered)
            continue
        # Escaping can expand a character to several bytes. Small raw pieces
        # keep every generated HTML fragment independently valid.
        for piece in textwrap.wrap(raw_line, width=max(80, max_length // 6), break_long_words=True, break_on_hyphens=False):
            rendered_lines.append(_format_line(piece))

    chunks: list[str] = []
    current = ""
    for line in rendered_lines:
        candidate = f"{current}\n{line}" if current else line
        if current and len(candidate) > max_length:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


async def send_summary(bot: Any, chat_id: int, summary: str) -> None:
    for chunk in telegram_summary_chunks(summary):
        await bot.send_message(
            chat_id=chat_id,
            text=chunk,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
