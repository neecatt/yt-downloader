from __future__ import annotations

import hmac
import os
from typing import Any

from fastapi import Body, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from . import activity_store
from .limits import SlidingWindowLimiter


ADMIN_REQUESTS_PER_MINUTE = min(300, max(10, int(os.getenv("ADMIN_REQUESTS_PER_MINUTE", "60"))))
_REQUEST_LIMITER = SlidingWindowLimiter(max_keys=10000)


def _authorized(authorization: str | None) -> bool:
    expected = os.getenv("ADMIN_API_TOKEN", "")
    provided = authorization.removeprefix("Bearer ").strip() if authorization else ""
    return bool(expected) and hmac.compare_digest(provided, expected)


def _client_key(request: Request) -> str:
    # Do not trust user-controlled forwarding headers for authorization. The
    # ASGI peer is the only stable identity available without a proxy module.
    return request.client.host if request.client else "unknown"


def _rate_limit(request: Request) -> None:
    if not _REQUEST_LIMITER.allow(_client_key(request), limit=ADMIN_REQUESTS_PER_MINUTE, window_seconds=60):
        raise HTTPException(status_code=429, detail="Too many requests", headers={"Retry-After": "60"})


def create_app() -> FastAPI:
    activity_store.initialize()
    app = FastAPI(title="Downloader Admin API", docs_url=None, redoc_url=None)

    @app.get("/health")
    async def health(request: Request) -> dict[str, str]:
        _rate_limit(request)
        return {"status": "ok"}

    @app.get("/admin/activity")
    async def activity(request: Request, authorization: str | None = Header(default=None), q: str | None = Query(default=None), platform: str | None = Query(default=None), status: str | None = Query(default=None), page: int = Query(default=1, ge=1), page_size: int = Query(default=25, alias="pageSize", ge=1, le=100)) -> JSONResponse:
        _rate_limit(request)
        if not _authorized(authorization):
            raise HTTPException(status_code=401, detail="Unauthorized")
        try:
            result = activity_store.query_events(q=q, platform=platform, status=status, page=page, page_size=page_size)
        except Exception:
            raise HTTPException(status_code=503, detail="Activity database unavailable") from None
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    @app.delete("/admin/activity")
    async def delete_activity(request: Request, payload: dict[str, Any] = Body(...), authorization: str | None = Header(default=None)) -> JSONResponse:
        _rate_limit(request)
        if not _authorized(authorization):
            raise HTTPException(status_code=401, detail="Unauthorized")
        event_ids = payload.get("ids")
        if not isinstance(event_ids, list) or not event_ids or len(event_ids) > 100 or not all(isinstance(event_id, str) for event_id in event_ids):
            raise HTTPException(status_code=400, detail="Provide between 1 and 100 event IDs")
        try:
            deleted = activity_store.delete_events(event_ids)
        except Exception:
            raise HTTPException(status_code=503, detail="Activity database unavailable") from None
        return JSONResponse({"deleted": deleted}, headers={"Cache-Control": "no-store"})

    return app
