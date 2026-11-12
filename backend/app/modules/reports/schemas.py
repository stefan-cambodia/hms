"""Report payloads. Amounts are null unless the user has reports.financial;
ratios are null when their denominator is zero (never a misleading 0)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.core.schemas import OutputModel


class Kpis(OutputModel):
    rooms: int
    out_of_service: int
    available: int
    sold: int
    occupancy: Decimal | None
    revenue: Decimal | None
    adr: Decimal | None
    revpar: Decimal | None


class DailyKpis(Kpis):
    date: date


class Bookings(OutputModel):
    created: int
    cancelled: int
    cancellation_rate: Decimal | None
    arrivals: int
    no_shows: int
    no_show_rate: Decimal | None
    average_stay: Decimal | None
    average_lead_days: Decimal | None


class ShareRow(OutputModel):
    sold: int
    share: Decimal | None
    revenue: Decimal | None
    revenue_share: Decimal | None
    adr: Decimal | None


class SourceRow(ShareRow):
    source: str


class RatePlanRow(ShareRow):
    rate_plan_id: uuid.UUID | None


class RoomTypeRow(Kpis):
    room_type_id: uuid.UUID


class OtherRevenue(OutputModel):
    services: Decimal
    fees: Decimal
    adjustments: Decimal
    restaurant: Decimal
    vehicles: Decimal
    total: Decimal
    restaurant_checks: int
    rentals: int


class CompareDaily(OutputModel):
    date: date
    occupancy: Decimal | None
    adr: Decimal | None
    revpar: Decimal | None


class Comparison(OutputModel):
    kind: str
    start: date
    end: date
    totals: Kpis
    bookings: Bookings
    daily: list[CompareDaily]
    other_revenue: OtherRevenue | None


class PerformanceOut(OutputModel):
    start: date
    end: date
    currency: str
    financial: bool
    totals: Kpis
    bookings: Bookings
    daily: list[DailyKpis]
    by_source: list[SourceRow]
    by_rate_plan: list[RatePlanRow]
    by_room_type: list[RoomTypeRow]
    other_revenue: OtherRevenue | None
    compare: Comparison | None


class ForecastTotals(Kpis):
    pickup: int


class ForecastDay(DailyKpis):
    pickup: int
    pickup_revenue: Decimal | None


class ForecastOut(OutputModel):
    start: date
    end: date
    currency: str
    financial: bool
    totals: ForecastTotals
    daily: list[ForecastDay]


class NextDay(OutputModel):
    date: date
    occupancy: Decimal | None
    sold: int
    available: int


class TodayOut(OutputModel):
    date: date
    currency: str
    financial: bool
    tonight: Kpis
    arrivals_due: int
    arrived: int
    departures_due: int
    departed: int
    in_house: int
    month_to_date: Kpis
    month_to_date_last_year: Kpis
    next_days: list[NextDay]
