from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import text

import app.models  # noqa: F401  (register all ORM models)
from app.core.config import get_settings
from app.core.db import dispose_engine, sessionmaker
from app.core.dbroles import runtime_role_posture
from app.core.errors import install_error_handlers
from app.modules.accounts.router import router as accounts_router
from app.modules.auth.router import router as auth_router
from app.modules.backups.router import router as backups_router
from app.modules.billing.router import router as billing_router
from app.modules.channels.router import router as channels_router
from app.modules.channels.worker import worker as channel_worker
from app.modules.facilities.router import router as facilities_router
from app.modules.frontdesk.router import router as frontdesk_router
from app.modules.guests.router import router as guests_router
from app.modules.hotels.router import router as hotels_router
from app.modules.housekeeping.router import router as housekeeping_router
from app.modules.maintenance.router import router as maintenance_router
from app.modules.media.images import MAX_UPLOAD_BYTES
from app.modules.media.router import router as media_router
from app.modules.nightaudit.router import router as nightaudit_router
from app.modules.pricing.router import router as pricing_router
from app.modules.realtime.hub import hub
from app.modules.realtime.router import router as realtime_router
from app.modules.reports.router import router as reports_router
from app.modules.reservations.router import router as reservations_router
from app.modules.restaurant.router import router as restaurant_router
from app.modules.rooms.router import router as rooms_router
from app.modules.users.router import router as users_router
from app.modules.vehicles.router import router as vehicles_router

API_PREFIX = "/api/v1"
# One photo upload plus the multipart envelope.
MAX_REQUEST_BYTES = MAX_UPLOAD_BYTES + 1024 * 1024


logger = logging.getLogger("hms")


async def _check_database_role() -> None:
    """Row-level security and the append-only grants only protect anything if
    the API connects with the least-privilege role (migration 0010)."""
    async with sessionmaker()() as db:
        posture = await runtime_role_posture(db)
    if not posture.problems:
        return
    message = (
        f"the API connects to PostgreSQL as {posture.role!r}, which {', '.join(posture.problems)}: "
        "row-level security and append-only protections are not in force. Set HMS_DATABASE_URL to "
        "the application role and run `hms db-roles` (installation guide, section 2)."
    )
    if get_settings().env == "production":
        raise RuntimeError(message)
    logger.warning(message)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logging.basicConfig(level=get_settings().log_level)
    await _check_database_role()
    await hub.start()
    settings = get_settings()
    if settings.channel_worker_enabled:
        channel_worker.interval = settings.channel_worker_interval_seconds
        channel_worker.start()
    try:
        yield
    finally:
        await channel_worker.stop()
        await hub.stop()
        await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="HMS API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs" if settings.enable_docs else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.enable_docs else None,
    )
    install_error_handlers(app)

    @app.middleware("http")
    async def request_context(request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        # Refuse oversized bodies before they are read (the largest legitimate
        # request is one photo upload); Caddy enforces the same in production.
        length = request.headers.get("content-length", "")
        if length.isdigit() and int(length) > MAX_REQUEST_BYTES:
            return JSONResponse(
                status_code=413,
                content={
                    "error": {
                        "code": "FILE_TOO_LARGE",
                        "message": "Request body too large",
                        "params": {"max_mb": MAX_UPLOAD_BYTES // (1024 * 1024)},
                        "fields": [],
                    }
                },
                headers={"X-Request-ID": request_id, "X-Content-Type-Options": "nosniff"},
            )
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    api = APIRouter(prefix=API_PREFIX)

    @api.get("/health", tags=["system"])
    async def health() -> dict:
        async with sessionmaker()() as db:
            await db.execute(text("SELECT 1"))
        # "service" lets clients (the desktop shell) recognise an HMS server.
        return {"status": "ok", "service": "hms", "version": app.version, "realtime": hub.listening.is_set()}

    api.include_router(auth_router)
    api.include_router(hotels_router)
    api.include_router(rooms_router)
    api.include_router(facilities_router)
    api.include_router(users_router)
    api.include_router(guests_router)
    api.include_router(reservations_router)
    api.include_router(pricing_router)
    api.include_router(billing_router)
    api.include_router(frontdesk_router)
    api.include_router(housekeeping_router)
    api.include_router(maintenance_router)
    api.include_router(restaurant_router)
    api.include_router(vehicles_router)
    api.include_router(channels_router)
    api.include_router(reports_router)
    api.include_router(nightaudit_router)
    api.include_router(media_router)
    api.include_router(accounts_router)
    api.include_router(backups_router)
    api.include_router(realtime_router)
    app.include_router(api)
    return app


app = create_app()
