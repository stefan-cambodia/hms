from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request, Response
from sqlalchemy import text

import app.models  # noqa: F401  (register all ORM models)
from app.core.config import get_settings
from app.core.db import dispose_engine, sessionmaker
from app.core.errors import install_error_handlers
from app.modules.auth.router import router as auth_router
from app.modules.billing.router import router as billing_router
from app.modules.channels.router import router as channels_router
from app.modules.channels.worker import worker as channel_worker
from app.modules.facilities.router import router as facilities_router
from app.modules.frontdesk.router import router as frontdesk_router
from app.modules.guests.router import router as guests_router
from app.modules.hotels.router import router as hotels_router
from app.modules.housekeeping.router import router as housekeeping_router
from app.modules.maintenance.router import router as maintenance_router
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


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logging.basicConfig(level=get_settings().log_level)
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
        return {"status": "ok", "realtime": hub.listening.is_set()}

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
    api.include_router(realtime_router)
    app.include_router(api)
    return app


app = create_app()
