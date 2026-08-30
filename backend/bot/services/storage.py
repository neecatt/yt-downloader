"""Private R2-compatible object storage service."""

from __future__ import annotations

import logging
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

from ..observability import log_timing

LOG = logging.getLogger("downloader_bot.storage")


def configured(endpoint_url: str | None, access_key: str | None, secret_key: str | None, bucket: str | None) -> bool:
    return bool(endpoint_url and access_key and secret_key and bucket and urlsplit(endpoint_url).scheme == "https")


def client(endpoint_url: str | None, access_key: str | None, secret_key: str | None, bucket: str | None) -> Any:
    if not configured(endpoint_url, access_key, secret_key, bucket):
        raise RuntimeError("R2 storage is not configured")
    import boto3
    parsed = urlsplit(endpoint_url)
    path_parts = [part for part in parsed.path.split("/") if part]
    if path_parts and path_parts[-1] == bucket:
        endpoint_url = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
    return boto3.client("s3", endpoint_url=endpoint_url, aws_access_key_id=access_key, aws_secret_access_key=secret_key, region_name="auto")


def upload(
    filename: Path,
    info: dict[str, Any],
    extension: str,
    *,
    client_factory: Callable[[], Any],
    bucket: str,
    public_base_url: str | None,
    url_ttl: int,
    retention_seconds: int,
    schedule_delete: Callable[..., None],
    upload_concurrency: int,
) -> tuple[str, str]:
    started = time.perf_counter()
    from boto3.s3.transfer import TransferConfig
    title = info.get("title", "download")
    name = re_safe_filename(title, extension)
    object_key = f"downloads/{datetime.now(timezone.utc):%Y/%m/%d}/{secrets.token_urlsafe(12)}-{name}"
    storage_client = client_factory()
    transfer_config = TransferConfig(multipart_threshold=32 * 1024 * 1024, multipart_chunksize=16 * 1024 * 1024, max_concurrency=upload_concurrency, use_threads=True)
    storage_client.upload_file(str(filename), bucket, object_key, ExtraArgs={"ContentType": {"mp3": "audio/mpeg", "mp4": "video/mp4"}.get(extension, "application/octet-stream")}, Config=transfer_config)
    schedule_delete(client_factory, bucket, object_key, delay_seconds=retention_seconds)
    if public_base_url:
        LOG.warning("R2_PUBLIC_BASE_URL is ignored; temporary downloads require private presigned URLs")
    url = storage_client.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": object_key, "ResponseContentDisposition": f'attachment; filename="{name}"'}, ExpiresIn=url_ttl)
    log_timing(LOG, "r2_upload_finished", started, size_bytes=filename.stat().st_size, extension=extension)
    return url, object_key


def delete(object_key: str, *, client_factory: Callable[[], Any], bucket: str) -> None:
    """Delete one temporary object without exposing storage details to handlers."""
    if not object_key:
        return
    started = time.perf_counter()
    try:
        client_factory().delete_object(Bucket=bucket, Key=object_key)
        log_timing(LOG, "r2_transcription_cleanup_finished", started)
    except Exception:
        LOG.warning("Could not immediately delete temporary transcription object", exc_info=True)


def re_safe_filename(title: str, extension: str) -> str:
    import re
    clean = re.sub(r"[^\w\-. ]+", "", str(title)).strip(" .") or "download"
    return f"{clean[:80]}.{extension}"
