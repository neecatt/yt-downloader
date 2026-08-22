from __future__ import annotations

import hmac
import os
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse

from . import activity_store


def _authorized(authorization: str | None) -> bool:
    expected = os.getenv("ADMIN_API_TOKEN", "")
    provided = authorization.removeprefix("Bearer ").strip() if authorization else ""
    return bool(expected) and hmac.compare_digest(provided, expected)


def create_app() -> FastAPI:
    activity_store.initialize()
    app = FastAPI(title="Downloader Admin API", docs_url=None, redoc_url=None)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/admin/activity")
    async def activity(authorization: str | None = Header(default=None), q: str | None = Query(default=None), platform: str | None = Query(default=None), status: str | None = Query(default=None), page: int = Query(default=1, ge=1), page_size: int = Query(default=25, alias="pageSize", ge=1, le=100)) -> JSONResponse:
        if not _authorized(authorization):
            raise HTTPException(status_code=401, detail="Unauthorized")
        try:
            result = activity_store.query_events(q=q, platform=platform, status=status, page=page, page_size=page_size)
        except Exception:
            raise HTTPException(status_code=503, detail="Activity database unavailable") from None
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    return app
