from __future__ import annotations

"""Route yt-dlp diagnostics through sanitized application logging."""

import logging

from ..platforms.security import safe_log_error

LOG = logging.getLogger("downloader_bot.ytdlp")


class YtdlpLogger:
    def debug(self, message: str) -> None:
        # yt-dlp sends both progress and debug messages here. Debug output can
        # contain cookies, signed media URLs and generated PO tokens.
        if "[pot:bgutil:http] Generating a " in message and not message.startswith("[debug]"):
            LOG.info("event=ytdlp_po_token_requested provider=bgutil_http")

    def info(self, message: str) -> None:
        self.debug(message)

    def warning(self, message: str) -> None:
        LOG.warning("event=ytdlp_warning message=%s", safe_log_error(RuntimeError(message)))

    def error(self, message: str) -> None:
        LOG.error("event=ytdlp_error message=%s", safe_log_error(RuntimeError(message)))
