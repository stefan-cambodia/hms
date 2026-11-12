"""Availability, rates and restrictions (ARI) for a channel: current values
from the inventory and pricing engines, compared with the values the channel
last acknowledged, turned into the smallest set of updates.

Nothing here is provider specific. Values are computed when the sync runs
(the change queue holds date ranges, not values), so a delayed sync never
sends outdated data.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.money import ZERO, round_money
from app.modules.channels.adapters.base import InventoryUpdate, RateUpdate, RestrictionUpdate
from app.modules.channels.models import (
    ChannelConnection,
    ChannelInventoryState,
    ChannelRateMap,
    ChannelRateState,
    ChannelRoomMap,
)
from app.modules.hotels.models import Hotel
from app.modules.inventory import service as inventory
from app.modules.pricing import engine
from app.modules.pricing import service as pricing
from app.modules.rooms.models import RoomType

Interval = tuple[date, date]  # [start, end)


@dataclass(frozen=True)
class RateValues:
    price: Decimal
    currency: str
    closed: bool
    closed_to_arrival: bool
    closed_to_departure: bool
    min_stay: int | None
    max_stay: int | None


RESTRICTION_FIELDS = ("closed", "closed_to_arrival", "closed_to_departure", "min_stay", "max_stay")


@dataclass
class Plan:
    """What to send, and how to record it once the channel acknowledged it."""

    inventory: list[InventoryUpdate]
    restrictions: list[RestrictionUpdate]
    rates: list[RateUpdate]
    inventory_rows: list[dict[str, Any]]
    rate_rows: list[dict[str, Any]]  # price + restrictions, written once both are acknowledged

    @property
    def empty(self) -> bool:
        return not (self.inventory or self.restrictions or self.rates)


def merge_intervals(intervals: Iterable[Interval]) -> list[Interval]:
    out: list[Interval] = []
    for start, end in sorted(intervals):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def _nights(intervals: list[Interval]) -> list[date]:
    days: list[date] = []
    for start, end in intervals:
        d = start
        while d < end:
            days.append(d)
            d += timedelta(days=1)
    return days


def _runs(items: list[tuple[date, Any]]) -> list[tuple[date, date, Any]]:
    """Consecutive nights with equal values → (first, last inclusive, value)."""
    runs: list[tuple[date, date, Any]] = []
    for day, value in sorted(items, key=lambda x: x[0]):
        if runs and runs[-1][2] == value and runs[-1][1] + timedelta(days=1) == day:
            runs[-1] = (runs[-1][0], day, value)
        else:
            runs.append((day, day, value))
    return runs


async def _amount_factor(db: AsyncSession, hotel: Hotel, rt: RoomType, after_tax: bool):  # type: ignore[no-untyped-def]
    """Function price → amount sent: the price plus exclusive accommodation
    taxes for one night at standard occupancy (after tax), or the price
    without any tax (before tax)."""
    taxes = await pricing.active_taxes(db, hotel.id, "accommodation")

    def convert(price: Decimal) -> Decimal:
        lines = pricing.compute_taxes(taxes, price, 1, rt.base_occupancy, hotel.currency_code)
        if after_tax:
            return price + sum((t.amount for t in lines if not t.is_inclusive), ZERO)
        return round_money(
            price - sum((t.amount for t in lines if t.is_inclusive), ZERO), hotel.currency_code
        )

    return convert


async def build_plan(
    db: AsyncSession,
    conn: ChannelConnection,
    ranges: dict[uuid.UUID | None, list[Interval]],
    *,
    today: date,
    horizon_end: date,
) -> Plan:
    """`ranges`: room type id (None = every category) → date intervals to check."""
    hotel = await db.get(Hotel, conn.hotel_id)
    assert hotel is not None
    room_maps = {
        m.room_type_id: m.external_code
        for m in await db.scalars(select(ChannelRoomMap).where(ChannelRoomMap.connection_id == conn.id))
    }
    rate_maps = list(await db.scalars(select(ChannelRateMap).where(ChannelRateMap.connection_id == conn.id)))
    every = ranges.get(None, [])
    per_type: dict[uuid.UUID, list[Interval]] = {}
    for rt_id in room_maps:
        clipped = [
            (max(s, today), min(e, horizon_end))
            for s, e in [*every, *ranges.get(rt_id, [])]
            if min(e, horizon_end) > max(s, today)
        ]
        if clipped:
            per_type[rt_id] = merge_intervals(clipped)
    plan = Plan([], [], [], [], [])
    if not per_type:
        return plan
    start = min(i[0][0] for i in per_type.values())
    end = max(i[-1][1] for i in per_type.values())
    types = {t.id: t for t in await db.scalars(select(RoomType).where(RoomType.id.in_(list(per_type))))}
    avail = {
        (a.room_type_id, a.night): a.available
        for a in await inventory.availability(db, conn.hotel_id, start, end, list(per_type))
    }
    pctx = await pricing.load_context(db, conn.hotel_id, start, end)
    after_tax = conn.settings.get("rate_amount", "after_tax") != "before_tax"

    inv_state = {
        (s.room_type_id, s.night): s.available
        for s in await db.scalars(
            select(ChannelInventoryState).where(
                ChannelInventoryState.connection_id == conn.id,
                ChannelInventoryState.room_type_id.in_(list(per_type)),
                ChannelInventoryState.night >= start,
                ChannelInventoryState.night < end,
            )
        )
    }
    rate_state = {
        (s.room_type_id, s.rate_plan_id, s.night): s
        for s in await db.scalars(
            select(ChannelRateState).where(
                ChannelRateState.connection_id == conn.id,
                ChannelRateState.room_type_id.in_(list(per_type)),
                ChannelRateState.night >= start,
                ChannelRateState.night < end,
            )
        )
    }

    for rt_id, intervals in per_type.items():
        rt = types.get(rt_id)
        if rt is None:
            continue
        room_code = room_maps[rt_id]
        nights = _nights(intervals)
        # Availability (room level). Inactive category or oversold → 0.
        changed: list[tuple[date, int]] = []
        for night in nights:
            value = max(0, avail.get((rt_id, night), 0)) if rt.is_active else 0
            if inv_state.get((rt_id, night)) != value:
                changed.append((night, value))
                plan.inventory_rows.append(
                    {"connection_id": conn.id, "room_type_id": rt_id, "night": night, "available": value}
                )
        for first, last, value in _runs(changed):
            plan.inventory.append(InventoryUpdate(room_code, first, last, value))

        convert = await _amount_factor(db, hotel, rt, after_tax)
        for rm in (m for m in rate_maps if m.room_type_id == rt_id):
            rp = pctx.plans.get(rm.rate_plan_id)
            if rp is None:
                continue
            price_changes: list[tuple[date, tuple[Decimal, str]]] = []
            restriction_changes: list[tuple[date, tuple[tuple[str, Any], ...]]] = []
            for night in nights:
                value = current_rate(pctx, rp, rt, night, today, convert)
                old = rate_state.get((rt_id, rp.id, night))
                if old is None or old.price != value.price or old.currency != value.currency:
                    price_changes.append((night, (value.price, value.currency)))
                diff = tuple(
                    (f, getattr(value, f))
                    for f in RESTRICTION_FIELDS
                    if old is None or getattr(old, f) != getattr(value, f)
                )
                if diff:
                    restriction_changes.append((night, diff))
                if old is None or diff or old.price != value.price or old.currency != value.currency:
                    plan.rate_rows.append(
                        {
                            "connection_id": conn.id,
                            "room_type_id": rt_id,
                            "rate_plan_id": rp.id,
                            "night": night,
                            "price": value.price,
                            "currency": value.currency,
                            **{f: getattr(value, f) for f in RESTRICTION_FIELDS},
                        }
                    )
            for first, last, (price, currency) in _runs(price_changes):
                plan.rates.append(
                    RateUpdate(room_code, rm.external_code, first, last, price, currency, after_tax)
                )
            for first, last, diff in _runs(restriction_changes):
                values = dict(diff)
                plan.restrictions.append(
                    RestrictionUpdate(
                        room_code,
                        rm.external_code,
                        first,
                        last,
                        closed=values.get("closed"),
                        closed_to_arrival=values.get("closed_to_arrival"),
                        closed_to_departure=values.get("closed_to_departure"),
                        # 0 = no limit (the adapter knows how the provider removes a limit)
                        min_stay=(values["min_stay"] or 0) if "min_stay" in values else None,
                        max_stay=(values["max_stay"] or 0) if "max_stay" in values else None,
                    )
                )
    return plan


def current_rate(
    pctx: engine.PricingContext, plan: Any, rt: RoomType, night: date, today: date, convert: Any
) -> RateValues:
    """Price and restrictions of one room category / rate plan / night, as
    the rate grid shows them, with the plan's own conditions (inactive,
    validity, booking window, categories) expressed as a stop sell."""
    price, _ = engine.base_night_rate(pctx, plan, rt, night)
    row, _ = engine.restriction_row(pctx, plan, rt.id, night)
    lead = (night - today).days
    plan_closed = (
        not plan.is_active
        or not rt.is_active
        or (plan.room_type_ids and rt.id not in plan.room_type_ids)
        or (plan.valid_from is not None and night < plan.valid_from)
        or (plan.valid_to is not None and night > plan.valid_to)
        or (plan.min_advance_days is not None and lead < plan.min_advance_days)
        or (plan.max_advance_days is not None and lead > plan.max_advance_days)
    )
    min_stay = row.min_stay if row and row.min_stay and row.min_stay > 1 else None
    max_stay = row.max_stay if row and row.max_stay else None
    if min_stay and max_stay and min_stay > max_stay:  # never send MinLOS > MaxLOS
        max_stay = min_stay
    return RateValues(
        price=round_money(convert(price), pctx.currency),
        currency=pctx.currency,
        closed=bool(plan_closed or (row and row.closed) or price <= 0),
        closed_to_arrival=bool(row and row.closed_to_arrival),
        closed_to_departure=bool(row and row.closed_to_departure),
        min_stay=min_stay,
        max_stay=max_stay,
    )


async def record_inventory(db: AsyncSession, rows: list[dict[str, Any]]) -> None:
    for chunk in (rows[i : i + 1000] for i in range(0, len(rows), 1000)):
        stmt = insert(ChannelInventoryState).values(chunk)
        await db.execute(
            stmt.on_conflict_do_update(
                index_elements=["connection_id", "room_type_id", "night"],
                set_={"available": stmt.excluded.available, "acked_at": stmt.excluded.acked_at},
            )
        )


async def record_rates(db: AsyncSession, rows: list[dict[str, Any]]) -> None:
    for chunk in (rows[i : i + 1000] for i in range(0, len(rows), 1000)):
        stmt = insert(ChannelRateState).values(chunk)
        await db.execute(
            stmt.on_conflict_do_update(
                index_elements=["connection_id", "room_type_id", "rate_plan_id", "night"],
                set_={
                    c: getattr(stmt.excluded, c)
                    for c in ("price", "currency", *RESTRICTION_FIELDS, "acked_at")
                },
            )
        )
