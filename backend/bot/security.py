from __future__ import annotations

import ipaddress
import logging
import re
import socket
from urllib.parse import urlparse, urlsplit, urlunsplit

LOG = logging.getLogger("downloader_bot")
URL_RE = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
SUPPORTED_CHAT_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be",
    "tiktok.com", "www.tiktok.com", "vm.tiktok.com", "vt.tiktok.com",
    "instagram.com", "www.instagram.com", "facebook.com", "www.facebook.com",
    "m.facebook.com", "web.facebook.com", "fb.watch",
    "x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com",
    "linkedin.com", "www.linkedin.com", "lnkd.in",
}


def validate_donation_url(value: str) -> str | None:
    parsed = urlparse(value)
    if not value or parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        if value:
            LOG.warning("DONATION_URL ignored because it is not a valid HTTPS URL")
        return None
    return value


def extract_url(text: str, *, any_https: bool = False, max_length: int = 4096) -> str | None:
    match = URL_RE.search(text)
    if not match:
        return None
    candidate = match.group(0).rstrip(".,!?)]}")
    if len(candidate) > max(256, max_length):
        return None
    parsed = urlparse(candidate)
    try:
        host = parsed.hostname.lower().rstrip(".") if parsed.hostname else ""
    except ValueError:
        return None
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or not host:
        return None
    try:
        host_ip = ipaddress.ip_address(host)
    except ValueError:
        host_ip = None
    if host in {"localhost", "localhost.localdomain"} or (host_ip and (host_ip.is_private or host_ip.is_loopback or host_ip.is_link_local)):
        return None
    return candidate if any_https or host in SUPPORTED_CHAT_HOSTS else None


def validate_remote_url(url: str) -> None:
    parsed = urlparse(url)
    host = parsed.hostname
    if parsed.scheme != "https" or not host:
        raise ValueError("Only HTTPS URLs are allowed")
    try:
        addresses = {ipaddress.ip_address(result[4][0]) for result in socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)}
    except (OSError, ValueError):
        raise ValueError("The source host could not be resolved safely") from None
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError("The source host resolves to a non-public network")


def safe_log_url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path[:160], "", ""))


def safe_log_error(exc: Exception) -> str:
    return re.sub(r"https?://[^\s]+", "[url-redacted]", str(exc))[:500]
