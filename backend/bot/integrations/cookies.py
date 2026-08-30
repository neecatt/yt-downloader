from __future__ import annotations

import base64
import os
import tempfile
from pathlib import Path


def prepare_cookie_file(encoded_value: str | None, file_value: str | None) -> str | None:
    if not encoded_value:
        return file_value
    try:
        encoded = b"".join(encoded_value.encode("ascii").split())
        cookie_data = base64.b64decode(encoded, validate=True)
        if not cookie_data.startswith((b"# HTTP Cookie File", b"# Netscape HTTP Cookie File")):
            raise ValueError("cookie data is not in Netscape format")
    except (ValueError, base64.binascii.Error) as exc:
        raise RuntimeError("YTDLP_COOKIES_B64 must be valid base64 Netscape cookies") from exc
    fd, cookie_name = tempfile.mkstemp(prefix="yt-dlp-cookies-", suffix=".txt")
    cookie_path = Path(cookie_name)
    with os.fdopen(fd, "wb") as cookie_file:
        cookie_file.write(cookie_data)
    cookie_path.chmod(0o600)
    return str(cookie_path)
