"""Analytics: hotel KPIs, breakdowns, forecast and the dashboard figures.

This module is the single place where the indicators are defined.

* **Rooms in the hotel** (per night): rooms in service on that night
  (`room_service_periods`, kept when rooms are created, deactivated or
  reactivated, so a room taken out of service still counts in the periods it
  was there), and any room sold that night (history entered later).
* **Out of service**: room-nights blocked (maintenance, out of order, owner use).
* **Available** = rooms − out of service.
* **Sold** (room-nights): nights of stays that occupy inventory — pending,
  confirmed, in-house or checked-out reservations; cancelled and no-show
  reservations release their nights. Complimentary nights (price 0) count.
* **Room revenue**: the nightly room prices of those nights, as charged —
  taxes included in prices stay included, taxes added on top are excluded
  (the convention used by every module: totals = price + added taxes).
* **Occupancy** = sold / available. **ADR** = room revenue / sold.
  **RevPAR** = room revenue / available (= ADR × occupancy).
* **Cancellation rate** (booking basis): reservations created in the period
  that are now cancelled / reservations created in the period.
* **No-show rate**: no-shows / (stays arriving in the period + no-shows).
* **Average length of stay** and **lead time** (days from booking to arrival)
  over stays arriving in the period.
* **Other revenue** (before taxes added on top): folio services, fees and
  adjustments by service date; restaurant checks closed in the period (by
  business date); vehicle rentals returned in the period. Restaurant or rental
  amounts charged to a room (folio "outlet" lines) are counted once, under the
  restaurant or the rentals, never again under the folio.

Revenue figures are returned only to users with reports.financial.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import HotelContext
from app.core.errors import ValidationFailed
from app.core.money import ZERO, round_money
from app.core.permissions import P
from app.modules.hotels.models import Hotel

MAX_RANGE_DAYS = 731
MAX_FORECAST_DAYS = 365
HUNDRED = Decimal(100)


def pct(part: int | Decimal, whole: int | Decimal) -> Decimal | None:
    """Percentage with one decimal, or None when the whole is zero."""
    if not whole:
        return None
    return (Decimal(part) * HUNDRED / Decimal(whole)).quantize(Decimal("0.1"))


def ratio(amount: Decimal, count: int, currency: str) -> Decimal | None:
    return round_money(amount / count, currency) if count else None


def check_range(start: date, end: date, max_days: int = MAX_RANGE_DAYS) -> None:
    if end <= start or (end - start).days > max_days:
        raise ValidationFailed("INVALID_RANGE", params={"max_days": max_days})


def previous_period(start: date, end: date) -> tuple[date, date]:
    length = end - start
    return start - length, start


def last_year(start: date, end: date) -> tuple[date, date]:
    def back(d: date) -> date:
        try:
            return d.replace(year=d.year - 1)
        except ValueError:  # 29 February
            return d.replace(year=d.year - 1, day=28)

    return back(start), back(end)


# --- raw aggregates ----------------------------------------------------------------

_SUPPLY = text(
    """
    WITH nights AS (
        SELECT d::date AS night
        FROM generate_series(CAST(:start AS date), CAST(:end AS date) - 1, interval '1 day') d
    )
    SELECT nt.night, r.room_type_id,
           count(r.id) AS rooms,
           count(b.room_id) AS blocked
    FROM nights nt
    JOIN rooms r ON r.hotel_id = :hotel
                AND (EXISTS (SELECT 1 FROM room_service_periods p
                             WHERE p.room_id = r.id AND p.period @> nt.night)
                     -- A room sold that night existed, whatever its record's
                     -- date (history entered after the rooms were set up).
                     OR EXISTS (SELECT 1 FROM room_allocations s
                                WHERE s.room_id = r.id AND s.room_block_id IS NULL AND s.period @> nt.night))
    LEFT JOIN LATERAL (
        SELECT a.room_id FROM room_allocations a
        WHERE a.room_id = r.id AND a.room_block_id IS NOT NULL AND a.period @> nt.night
        LIMIT 1
    ) b ON true
    GROUP BY nt.night, r.room_type_id
    """
)

_SOLD = text(
    """
    SELECT n.night, rr.room_type_id, res.source, n.rate_plan_id,
           count(*) AS sold, coalesce(sum(n.price), 0) AS revenue
    FROM reservation_nights n
    JOIN reservation_rooms rr ON rr.id = n.reservation_room_id
    JOIN reservations res ON res.id = rr.reservation_id
    WHERE n.hotel_id = :hotel AND n.night >= :start AND n.night < :end AND rr.occupies_inventory
    GROUP BY n.night, rr.room_type_id, res.source, n.rate_plan_id
    """
)

_PICKUP = text(
    """
    SELECT n.night, count(*) AS sold, coalesce(sum(n.price), 0) AS revenue
    FROM reservation_nights n
    JOIN reservation_rooms rr ON rr.id = n.reservation_room_id
    JOIN reservations res ON res.id = rr.reservation_id
    WHERE n.hotel_id = :hotel AND n.night >= :start AND n.night < :end AND rr.occupies_inventory
      AND res.created_at >= :since
    GROUP BY n.night
    """
)

_BOOKINGS = text(
    """
    SELECT count(*) AS created,
           count(*) FILTER (WHERE status = 'cancelled') AS cancelled
    FROM reservations
    WHERE hotel_id = :hotel
      AND (created_at AT TIME ZONE :tz)::date >= :start AND (created_at AT TIME ZONE :tz)::date < :end
    """
)

_ARRIVALS = text(
    """
    SELECT count(*) FILTER (WHERE rr.occupies_inventory) AS stays,
           count(*) FILTER (WHERE res.status = 'no_show') AS no_shows,
           coalesce(sum(rr.departure - rr.arrival) FILTER (WHERE rr.occupies_inventory), 0) AS nights,
           -- Booked on or after arrival (walk-in, entered late): lead time 0.
           coalesce(sum(greatest(rr.arrival - (res.created_at AT TIME ZONE :tz)::date, 0))
                    FILTER (WHERE rr.occupies_inventory), 0) AS lead_days
    FROM reservation_rooms rr
    JOIN reservations res ON res.id = rr.reservation_id
    WHERE rr.hotel_id = :hotel AND rr.arrival >= :start AND rr.arrival < :end
    """
)

_FOLIO = text(
    """
    SELECT kind, coalesce(sum(amount), 0) FROM folio_charges
    WHERE hotel_id = :hotel AND NOT is_void AND kind <> 'outlet'
      AND service_date >= :start AND service_date < :end
    GROUP BY kind
    """
)

_RESTAURANT = text(
    """
    SELECT coalesce(sum(total - tax_total), 0), count(*) FROM restaurant_orders
    WHERE hotel_id = :hotel AND status = 'closed' AND business_date >= :start AND business_date < :end
    """
)

_RENTALS = text(
    """
    SELECT coalesce(sum(total - tax_total), 0), count(*) FROM vehicle_rentals
    WHERE hotel_id = :hotel AND status = 'returned'
      AND (returned_at AT TIME ZONE :tz)::date >= :start AND (returned_at AT TIME ZONE :tz)::date < :end
    """
)

_DAY_MOVES = text(
    """
    SELECT
      count(*) FILTER (WHERE rr.arrival = :day AND res.status IN ('pending', 'confirmed')) AS arrivals_due,
      count(*) FILTER (WHERE rr.arrival = :day AND rr.checked_in_at IS NOT NULL) AS arrived,
      count(*) FILTER (
        WHERE rr.departure = :day AND rr.checked_in_at IS NOT NULL AND rr.checked_out_at IS NULL
      ) AS departures_due,
      count(*) FILTER (WHERE rr.departure = :day AND rr.checked_out_at IS NOT NULL) AS departed,
      count(*) FILTER (WHERE rr.checked_in_at IS NOT NULL AND rr.checked_out_at IS NULL) AS in_house
    FROM reservation_rooms rr
    JOIN reservations res ON res.id = rr.reservation_id
    WHERE rr.hotel_id = :hotel AND rr.occupies_inventory
      AND (rr.arrival = :day OR rr.departure = :day
           OR (rr.checked_in_at IS NOT NULL AND rr.checked_out_at IS NULL))
    """
)


@dataclass
class Facts:
    """Per-night supply and demand, with the dimensions the breakdowns need."""

    supply: dict[tuple[date, uuid.UUID], tuple[int, int]]  # (night, room type) -> (rooms, blocked)
    sold: list[tuple[date, uuid.UUID, str, uuid.UUID | None, int, Decimal]]


async def _facts(db: AsyncSession, hotel: Hotel, start: date, end: date) -> Facts:
    params = {"hotel": hotel.id, "start": start, "end": end, "tz": hotel.timezone}
    supply = {
        (night, rt): (int(rooms), int(blocked))
        for night, rt, rooms, blocked in await db.execute(_SUPPLY, params)
    }
    sold = [
        (night, rt, source, plan, int(n), Decimal(revenue))
        for night, rt, source, plan, n, revenue in await db.execute(_SOLD, params)
    ]
    return Facts(supply, sold)


def _nights(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days)]


# --- KPIs ------------------------------------------------------------------------------


def _kpis(
    rooms: int, blocked: int, sold: int, revenue: Decimal, currency: str, financial: bool
) -> dict[str, Any]:
    available = rooms - blocked
    return {
        "rooms": rooms,
        "out_of_service": blocked,
        "available": available,
        "sold": sold,
        "occupancy": pct(sold, available),
        "revenue": round_money(revenue, currency) if financial else None,
        "adr": ratio(revenue, sold, currency) if financial else None,
        "revpar": ratio(revenue, available, currency) if financial else None,
    }


async def _totals(db: AsyncSession, hotel: Hotel, start: date, end: date, financial: bool) -> dict[str, Any]:
    facts = await _facts(db, hotel, start, end)
    rooms = sum(r for r, _ in facts.supply.values())
    blocked = sum(b for _, b in facts.supply.values())
    sold = sum(s[4] for s in facts.sold)
    revenue = sum((s[5] for s in facts.sold), ZERO)
    return _kpis(rooms, blocked, sold, revenue, hotel.currency_code, financial)


async def _bookings(db: AsyncSession, hotel: Hotel, start: date, end: date) -> dict[str, Any]:
    params = {"hotel": hotel.id, "start": start, "end": end, "tz": hotel.timezone}
    created, cancelled = (await db.execute(_BOOKINGS, params)).one()
    stays, no_shows, nights, lead_days = (await db.execute(_ARRIVALS, params)).one()
    return {
        "created": int(created),
        "cancelled": int(cancelled),
        "cancellation_rate": pct(cancelled, created),
        "arrivals": int(stays),
        "no_shows": int(no_shows),
        "no_show_rate": pct(no_shows, stays + no_shows),
        "average_stay": (Decimal(nights) / stays).quantize(Decimal("0.1")) if stays else None,
        "average_lead_days": (Decimal(lead_days) / stays).quantize(Decimal("0.1")) if stays else None,
    }


async def _other_revenue(db: AsyncSession, hotel: Hotel, start: date, end: date) -> dict[str, Any]:
    params = {"hotel": hotel.id, "start": start, "end": end, "tz": hotel.timezone}
    folio = {kind: Decimal(amount) for kind, amount in await db.execute(_FOLIO, params)}
    restaurant, checks = (await db.execute(_RESTAURANT, params)).one()
    rentals, rental_count = (await db.execute(_RENTALS, params)).one()
    cur = hotel.currency_code
    values = {
        "services": round_money(folio.get("service", ZERO), cur),
        "fees": round_money(folio.get("fee", ZERO), cur),
        "adjustments": round_money(folio.get("adjustment", ZERO), cur),
        "restaurant": round_money(Decimal(restaurant), cur),
        "vehicles": round_money(Decimal(rentals), cur),
    }
    return {
        **values,
        "total": round_money(sum(values.values(), ZERO), cur),
        "restaurant_checks": int(checks),
        "rentals": int(rental_count),
    }


async def performance(
    db: AsyncSession, ctx: HotelContext, start: date, end: date, compare: str | None
) -> dict[str, Any]:
    """KPIs for [start, end) with daily series and breakdowns."""
    check_range(start, end)
    hotel = await db.get(Hotel, ctx.hotel_id)
    assert hotel is not None
    financial = ctx.has(P.REPORTS_FINANCIAL)
    cur = hotel.currency_code
    facts = await _facts(db, hotel, start, end)

    by_night_supply: dict[date, list[int]] = defaultdict(lambda: [0, 0])
    by_type_supply: dict[uuid.UUID, list[int]] = defaultdict(lambda: [0, 0])
    for (night, rt), (rooms, blocked) in facts.supply.items():
        by_night_supply[night][0] += rooms
        by_night_supply[night][1] += blocked
        by_type_supply[rt][0] += rooms
        by_type_supply[rt][1] += blocked
    by_night: dict[date, list[Any]] = defaultdict(lambda: [0, ZERO])
    by_type: dict[uuid.UUID, list[Any]] = defaultdict(lambda: [0, ZERO])
    by_source: dict[str, list[Any]] = defaultdict(lambda: [0, ZERO])
    by_plan: dict[uuid.UUID | None, list[Any]] = defaultdict(lambda: [0, ZERO])
    for night, rt, source, plan, n, revenue in facts.sold:
        for bucket, key in ((by_night, night), (by_type, rt), (by_source, source), (by_plan, plan)):
            bucket[key][0] += n
            bucket[key][1] += revenue

    daily = []
    for night in _nights(start, end):
        rooms, blocked = by_night_supply.get(night, [0, 0])
        sold, revenue = by_night.get(night, [0, ZERO])
        daily.append({"date": night, **_kpis(rooms, blocked, sold, revenue, cur, financial)})

    rooms = sum(v[0] for v in by_night_supply.values())
    blocked = sum(v[1] for v in by_night_supply.values())
    sold = sum(v[0] for v in by_night.values())
    revenue = sum((v[1] for v in by_night.values()), ZERO)
    totals = _kpis(rooms, blocked, sold, revenue, cur, financial)

    def share_rows(bucket: dict[Any, list[Any]], key_name: str) -> list[dict[str, Any]]:
        rows = []
        for key, (n, rev) in sorted(bucket.items(), key=lambda kv: (-kv[1][0], str(kv[0]))):
            rows.append(
                {
                    key_name: key,
                    "sold": n,
                    "share": pct(n, sold),
                    "revenue": round_money(rev, cur) if financial else None,
                    "revenue_share": pct(rev, revenue) if financial and revenue else None,
                    "adr": ratio(rev, n, cur) if financial else None,
                }
            )
        return rows

    room_types = []
    for rt in set(by_type_supply) | set(by_type):
        r_rooms, r_blocked = by_type_supply.get(rt, [0, 0])
        n, rev = by_type.get(rt, [0, ZERO])
        room_types.append({"room_type_id": rt, **_kpis(r_rooms, r_blocked, n, rev, cur, financial)})
    room_types.sort(key=lambda r: -(r["sold"]))

    result: dict[str, Any] = {
        "start": start,
        "end": end,
        "currency": cur,
        "financial": financial,
        "totals": totals,
        "bookings": await _bookings(db, hotel, start, end),
        "daily": daily,
        "by_source": share_rows(by_source, "source"),
        "by_rate_plan": share_rows(by_plan, "rate_plan_id"),
        "by_room_type": room_types,
        "other_revenue": await _other_revenue(db, hotel, start, end) if financial else None,
        "compare": None,
    }
    if compare in ("previous", "last_year"):
        c_start, c_end = previous_period(start, end) if compare == "previous" else last_year(start, end)
        result["compare"] = {
            "kind": compare,
            "start": c_start,
            "end": c_end,
            "totals": await _totals(db, hotel, c_start, c_end, financial),
            "bookings": await _bookings(db, hotel, c_start, c_end),
            "daily": [
                {"date": d["date"], "occupancy": d["occupancy"], "adr": d["adr"], "revpar": d["revpar"]}
                for d in (await _daily(db, hotel, c_start, c_end, financial))
            ],
            "other_revenue": await _other_revenue(db, hotel, c_start, c_end) if financial else None,
        }
    return result


async def _daily(
    db: AsyncSession, hotel: Hotel, start: date, end: date, financial: bool
) -> list[dict[str, Any]]:
    facts = await _facts(db, hotel, start, end)
    supply: dict[date, list[int]] = defaultdict(lambda: [0, 0])
    for (night, _), (rooms, blocked) in facts.supply.items():
        supply[night][0] += rooms
        supply[night][1] += blocked
    demand: dict[date, list[Any]] = defaultdict(lambda: [0, ZERO])
    for night, _, _, _, n, revenue in facts.sold:
        demand[night][0] += n
        demand[night][1] += revenue
    return [
        {
            "date": night,
            **_kpis(
                *supply.get(night, [0, 0]), *demand.get(night, [0, ZERO]), hotel.currency_code, financial
            ),
        }
        for night in _nights(start, end)
    ]


async def forecast(db: AsyncSession, ctx: HotelContext, days: int) -> dict[str, Any]:
    """Nights on the books from today, with the pickup of the last 7 days."""
    if not 1 <= days <= MAX_FORECAST_DAYS:
        raise ValidationFailed("INVALID_RANGE", params={"max_days": MAX_FORECAST_DAYS})
    hotel = await db.get(Hotel, ctx.hotel_id)
    assert hotel is not None
    financial = ctx.has(P.REPORTS_FINANCIAL)
    start = hotel.today()
    end = start + timedelta(days=days)
    daily = await _daily(db, hotel, start, end, financial)
    since = datetime.now(hotel.zone) - timedelta(days=7)
    pickup = {
        night: (int(n), Decimal(rev))
        for night, n, rev in await db.execute(
            _PICKUP, {"hotel": hotel.id, "start": start, "end": end, "since": since}
        )
    }
    for d in daily:
        n, rev = pickup.get(d["date"], (0, ZERO))
        d["pickup"] = n
        d["pickup_revenue"] = round_money(rev, hotel.currency_code) if financial else None
    totals = await _totals(db, hotel, start, end, financial)
    totals["pickup"] = sum(d["pickup"] for d in daily)
    return {
        "start": start,
        "end": end,
        "currency": hotel.currency_code,
        "financial": financial,
        "totals": totals,
        "daily": daily,
    }


async def today(db: AsyncSession, ctx: HotelContext) -> dict[str, Any]:
    """Dashboard: tonight, today's movements, month to date, next 14 nights."""
    hotel = await db.get(Hotel, ctx.hotel_id)
    assert hotel is not None
    financial = ctx.has(P.REPORTS_FINANCIAL)
    day = hotel.today()
    moves = (await db.execute(_DAY_MOVES, {"hotel": hotel.id, "day": day})).one()
    tonight = await _totals(db, hotel, day, day + timedelta(days=1), financial)
    month_start = day.replace(day=1)
    mtd_end = day + timedelta(days=1)
    mtd = await _totals(db, hotel, month_start, mtd_end, financial)
    ly_start, ly_end = last_year(month_start, mtd_end)
    mtd_last_year = await _totals(db, hotel, ly_start, ly_end, financial)
    next_days = await _daily(db, hotel, day, day + timedelta(days=14), financial)
    return {
        "date": day,
        "currency": hotel.currency_code,
        "financial": financial,
        "tonight": tonight,
        "arrivals_due": int(moves.arrivals_due),
        "arrived": int(moves.arrived),
        "departures_due": int(moves.departures_due),
        "departed": int(moves.departed),
        "in_house": int(moves.in_house),
        "month_to_date": mtd,
        "month_to_date_last_year": mtd_last_year,
        "next_days": [
            {"date": d["date"], "occupancy": d["occupancy"], "sold": d["sold"], "available": d["available"]}
            for d in next_days
        ],
    }
