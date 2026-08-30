"""Platform classification and media-post routing rules."""

from __future__ import annotations

from urllib.parse import urlsplit


IMAGE_POST_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif", "avif"}


def activity_platform(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    if "youtube" in host or host == "youtu.be":
        return "youtube"
    if "instagram" in host:
        return "instagram"
    if "facebook" in host or host == "fb.watch":
        return "facebook"
    if "tiktok" in host:
        return "tiktok"
    if "twitter" in host or host == "x.com":
        return "x"
    if "linkedin" in host or host == "lnkd.in":
        return "linkedin"
    return "other"


def is_image_or_carousel_info(info: dict | None) -> bool:
    if not info:
        return False
    if str(info.get("ext") or "").lower() in IMAGE_POST_EXTENSIONS:
        return True
    formats = [item for item in (info.get("formats") or []) if isinstance(item, dict)]
    return bool(formats) and all(str(item.get("ext") or "").lower() in IMAGE_POST_EXTENSIONS for item in formats)


def is_x_photo_link(url: str) -> bool:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    return host in {"x.com", "twitter.com", "mobile.twitter.com"} and "/photo/" in parsed.path.lower()


def should_analyze_media_type(url: str) -> bool:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path = parsed.path.lower()
    if is_x_photo_link(url):
        return True
    return (
        host == "instagram.com" and any(marker in path for marker in ("/p/", "/reel/", "/tv/"))
    ) or (host == "linkedin.com" and "/posts/" in path) or (
        host in {"facebook.com", "m.facebook.com", "web.facebook.com"}
        and any(marker in path for marker in ("/posts/", "/photos/", "/photo.php", "/permalink/"))
    )
