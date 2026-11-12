from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Query

from app.core.errors import Forbidden
from app.core.permissions import P
from app.modules.auth.deps import DB, hotel_ctx
from app.modules.reports import service
from app.modules.reports.schemas import ForecastOut, PerformanceOut, TodayOut

router = APIRouter(prefix="/hotels/{hotel_id}/reports", tags=["reports"])

View = hotel_ctx(P.REPORTS_VIEW)
Hotel = hotel_ctx(P.HOTEL_VIEW)


@router.get("/performance", response_model=PerformanceOut)
async def performance(
    ctx: View,
    db: DB,
    start: date,
    end: date = Query(description="exclusive (the night of `end` is not included)"),
    compare: Literal["previous", "last_year"] | None = None,
):
    return await service.performance(db, ctx, start, end, compare)


@router.get("/forecast", response_model=ForecastOut)
async def forecast(ctx: View, db: DB, days: int = Query(30, ge=1, le=service.MAX_FORECAST_DAYS)):
    return await service.forecast(db, ctx, days)


@router.get("/today", response_model=TodayOut)
async def today(ctx: Hotel, db: DB):
    """Dashboard figures: for anyone who sees reports or works with reservations."""
    if not (ctx.has(P.REPORTS_VIEW) or ctx.has(P.RESERVATIONS_VIEW)):
        raise Forbidden("PERMISSION_DENIED", params={"permission": P.REPORTS_VIEW})
    return await service.today(db, ctx)
