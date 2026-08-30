"""Typed environment-backed settings grouped by application responsibility."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _int(name: str, default: int, minimum: int = 0, maximum: int | None = None) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    value = max(minimum, value)
    return min(maximum, value) if maximum is not None else value


def _flag(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class TelegramSettings:
    token: str | None
    max_upload_bytes: int
    api_base_url: str | None
    api_file_base_url: str | None


@dataclass(frozen=True, slots=True)
class DownloadSettings:
    max_bytes: int
    max_url_length: int
    workers: int
    fragment_workers: int
    http_chunk_size_mb: int
    cookies_file: str | None
    cookies_b64: str | None
    proxy: str | None
    player_client: str | None
    po_token: str | None
    po_provider_url: str | None
    js_runtime: str | None
    delivery_mode: str
    allow_generic_https: bool


@dataclass(frozen=True, slots=True)
class StorageSettings:
    account_id: str | None
    endpoint_url: str | None
    api_token: str | None
    access_key_id: str | None
    secret_access_key: str | None
    bucket_name: str | None
    public_base_url: str | None
    presigned_url_ttl: int
    cleanup_interval: int
    upload_concurrency: int


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    state_ttl: int
    pending_delivery_ttl: int
    max_state_entries: int
    analyses_per_user_hour: int
    analyses_global_hour: int
    downloads_per_user_hour: int
    downloads_per_user_day: int
    downloads_global_hour: int


@dataclass(frozen=True, slots=True)
class AdminSettings:
    token: str
    enabled: bool
    host: str
    port: int


@dataclass(frozen=True, slots=True)
class DonationSettings:
    url: str
    prompts_enabled: bool
    cooldown_seconds: int


@dataclass(frozen=True, slots=True)
class AppSettings:
    telegram: TelegramSettings
    download: DownloadSettings
    storage: StorageSettings
    runtime: RuntimeSettings
    admin: AdminSettings
    donation: DonationSettings


def load_settings() -> AppSettings:
    account_id = os.getenv("R2_ACCOUNT_ID") or None
    endpoint = os.getenv("R2_ENDPOINT_URL") or (f"https://{account_id}.r2.cloudflarestorage.com" if account_id else None)
    api_token = os.getenv("R2_API_TOKEN") or None
    access_key = os.getenv("R2_ACCESS_KEY_ID") or None
    secret_key = os.getenv("R2_SECRET_ACCESS_KEY") or None
    if api_token and ":" in api_token:
        access_key, secret_key = api_token.split(":", 1)
    return AppSettings(
        telegram=TelegramSettings(
            token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
            max_upload_bytes=_int("TELEGRAM_MAX_UPLOAD_MB", 49, 1, 4096) * 1024 * 1024,
            api_base_url=os.getenv("TELEGRAM_API_BASE_URL") or None,
            api_file_base_url=os.getenv("TELEGRAM_API_FILE_BASE_URL") or None,
        ),
        download=DownloadSettings(
            max_bytes=_int("MAX_DOWNLOAD_MB", 2048, 1, 4096) * 1024 * 1024,
            max_url_length=_int("MAX_URL_LENGTH", 4096, 256),
            workers=_int("DOWNLOAD_WORKERS", 2, 1, 8),
            fragment_workers=_int("FRAGMENT_WORKERS", 4, 1, 16),
            http_chunk_size_mb=_int("HTTP_CHUNK_SIZE_MB", 10, 1),
            cookies_file=os.getenv("YTDLP_COOKIES_FILE") or None,
            cookies_b64=os.getenv("YTDLP_COOKIES_B64") or None,
            proxy=os.getenv("YTDLP_PROXY") or None,
            player_client=os.getenv("YTDLP_PLAYER_CLIENT") or None,
            po_token=os.getenv("YTDLP_PO_TOKEN") or None,
            po_provider_url=os.getenv("YTDLP_POT_PROVIDER_URL") or None,
            js_runtime=os.getenv("YTDLP_JS_RUNTIME") or None,
            delivery_mode=os.getenv("DELIVERY_MODE", "telegram").lower(),
            allow_generic_https=_flag("ALLOW_GENERIC_HTTPS"),
        ),
        storage=StorageSettings(
            account_id=account_id, endpoint_url=endpoint, api_token=api_token,
            access_key_id=access_key, secret_access_key=secret_key,
            bucket_name=os.getenv("R2_BUCKET_NAME") or None,
            public_base_url=os.getenv("R2_PUBLIC_BASE_URL") or None,
            presigned_url_ttl=_int("R2_PRESIGNED_URL_TTL_SECONDS", 86400, 60, 604800),
            cleanup_interval=_int("R2_CLEANUP_INTERVAL_SECONDS", 60, 30),
            upload_concurrency=_int("R2_UPLOAD_CONCURRENCY", 8, 1, 32),
        ),
        runtime=RuntimeSettings(
            state_ttl=_int("CALLBACK_STATE_TTL_SECONDS", 1800, 60, 86400),
            pending_delivery_ttl=_int("PENDING_DELIVERY_TTL_SECONDS", 900, 60, 3600),
            max_state_entries=_int("MAX_STATE_ENTRIES", 10000, 100, 100000),
            analyses_per_user_hour=_int("ANALYSES_PER_USER_PER_HOUR", 20, 1, 100),
            analyses_global_hour=_int("ANALYSES_GLOBAL_PER_HOUR", 300, 1, 2000),
            downloads_per_user_hour=_int("DOWNLOADS_PER_USER_PER_HOUR", 10, 1, 100),
            downloads_per_user_day=_int("DOWNLOADS_PER_USER_PER_DAY", 20, 10, 500),
            downloads_global_hour=_int("DOWNLOADS_GLOBAL_PER_HOUR", 100, 1, 1000),
        ),
        admin=AdminSettings(
            token=os.getenv("ADMIN_API_TOKEN", ""), enabled=_flag("ADMIN_API_ENABLED", True),
            host=os.getenv("ADMIN_API_HOST", "0.0.0.0"), port=_int("ADMIN_API_PORT", _int("PORT", 8080, 1), 1),
        ),
        donation=DonationSettings(
            url=os.getenv("DONATION_URL", "").strip(), prompts_enabled=_flag("DONATION_PROMPTS_ENABLED", True),
            cooldown_seconds=_int("DONATION_PROMPT_COOLDOWN_HOURS", 24, 0) * 3600,
        ),
    )


settings = load_settings()
