"""Application factory."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from trim import __version__
from trim.api.deps import AppContext
from trim.api.routes import router
from trim.auth import TokenAuthenticator
from trim.config import Settings, get_settings
from trim.connectors import build_connector
from trim.connectors.base import Connector, ConnectorError
from trim.db import Database, utcnow
from trim.services.notify import Notifier
from trim.services.remediation import NotUndoable, PartialFailure, ProviderFailure, RemediationError

log = logging.getLogger("trim")

MAX_BODY_BYTES = 64 * 1024
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
    "Cross-Origin-Resource-Policy": "same-origin",
}


def _error(status: int, code: str, detail: str, **extra) -> JSONResponse:
    return JSONResponse({"error": code, "detail": detail, **extra}, status_code=status)


def create_app(
    settings: Settings | None = None,
    *,
    db: Database | None = None,
    connector: Connector | None = None,
    clock: Callable[[], datetime] = utcnow,
    notifier: Notifier | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    db = db or Database(settings.database_url)
    if settings.env != "prod":
        db.create_all()  # production schema is managed by Alembic migrations
    app = FastAPI(
        title="Trim API",
        version=__version__,
        docs_url=None if settings.env == "prod" else "/api/docs",
        redoc_url=None,
        openapi_url=None if settings.env == "prod" else "/api/openapi.json",
    )
    app.state.ctx = AppContext(
        settings=settings,
        db=db,
        connector=connector or build_connector(settings, db),
        auth=TokenAuthenticator(settings.api_tokens),
        notifier=notifier or Notifier(settings.webhook_url),
        clock=clock,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
        allow_credentials=False,
        max_age=600,
    )

    @app.middleware("http")
    async def guard(request: Request, call_next):
        length = request.headers.get("content-length")
        if length is not None and (not length.isdigit() or int(length) > MAX_BODY_BYTES):
            return _error(413, "payload_too_large", "request body too large")
        response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException):
        resp = _error(exc.status_code, f"http_{exc.status_code}", str(exc.detail))
        for k, v in (exc.headers or {}).items():
            resp.headers[k] = v
        return resp

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        # Report field locations and messages, never the submitted values.
        problems = [f"{'.'.join(str(p) for p in e['loc'][1:])}: {e['msg']}" for e in exc.errors()]
        return _error(422, "invalid_request", "; ".join(problems)[:1000])

    @app.exception_handler(PartialFailure)
    async def partial(_: Request, exc: PartialFailure):
        return _error(502, exc.code, str(exc), decision_id=exc.decision_id)

    @app.exception_handler(ProviderFailure)
    async def provider(_: Request, exc: ProviderFailure):
        return _error(502, exc.code, str(exc))

    @app.exception_handler(NotUndoable)
    async def not_undoable(_: Request, exc: NotUndoable):
        return _error(409, exc.code, str(exc))

    @app.exception_handler(RemediationError)
    async def remediation(_: Request, exc: RemediationError):
        return _error(409, exc.code, str(exc))

    @app.exception_handler(ConnectorError)
    async def connector_error(_: Request, exc: ConnectorError):
        log.warning("connector error: %s", exc)
        return _error(502, "provider_error", "the identity provider call failed")

    app.include_router(router)
    return app


def app_factory() -> FastAPI:  # pragma: no cover - uvicorn entry point
    return create_app()
