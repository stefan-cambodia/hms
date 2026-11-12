"""Pricing engine — the single place where a night's price is decided.

Resolution for (rate plan P, room category T, night N):

1. **Base rate**
   a. an explicit price in the daily grid for (P, T, N) wins;
   b. else, if P derives from a parent plan, the parent's base rate for N is
      adjusted (percent, amount, or amount per person — e.g. breakfast);
   c. else the room's own base price, or the category's, adjusted by the
      *rate rules* (seasons and special events, weekday/weekend, occupancy)
      in priority order.
2. **Occupancy supplements** for guests beyond the category's standard
   occupancy (extra adult / extra child prices).
3. **Discount rules** that depend on the booking (long stay, last minute,
   early bird), applied on top of any price.
4. Rounded half-up to the currency's minor unit; never below zero.

Restrictions (stop sell, min/max stay, closed to arrival/departure) come from
the grid row of the plan, or of its nearest parent when the plan has none.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from app.core.money import ZERO, round_money
from app.modules.pricing.models import (
    DISCOUNT_RULE_KINDS,
    RATE_RULE_KINDS,
    DailyRate,
    PricingRule,
    RatePlan,
)
from app.modules.rooms.models import Room, RoomType

MAX_PLAN_DEPTH = 5


@dataclass
class PricingContext:
    hotel_id: uuid.UUID
    currency: str
    today: date
    plans: dict[uuid.UUID, RatePlan]
    default_plan: RatePlan
    daily: dict[tuple[uuid.UUID, uuid.UUID, date], DailyRate]
    rules: list[PricingRule]
    occupancy: dict[tuple[uuid.UUID, date], float] = field(default_factory=dict)

    def plan(self, plan_id: uuid.UUID | None) -> RatePlan:
        return self.plans[plan_id] if plan_id else self.default_plan

    def chain(self, plan: RatePlan) -> list[RatePlan]:
        out, seen = [plan], {plan.id}
        while out[-1].parent_rate_plan_id and len(out) < MAX_PLAN_DEPTH:
            parent = self.plans.get(out[-1].parent_rate_plan_id)
            if parent is None or parent.id in seen:
                break
            out.append(parent)
            seen.add(parent.id)
        return out


@dataclass
class Stay:
    room_type: RoomType
    room: Room | None
    arrival: date
    departure: date
    adults: int
    children: int
    rate_plan_id: uuid.UUID | None = None

    @property
    def nights(self) -> int:
        return (self.departure - self.arrival).days


@dataclass
class NightPrice:
    night: date
    price: Decimal
    source: str  # daily_rate | derived | base
    rate_plan_id: uuid.UUID
    rules: list[str] = field(default_factory=list)  # codes of the rules applied


def nights_between(arrival: date, departure: date) -> list[date]:
    return [arrival + timedelta(days=i) for i in range((departure - arrival).days)]


def _adjust(price: Decimal, mode: str, value: Decimal) -> Decimal:
    if mode == "percent":
        return price * (Decimal(100) + value) / Decimal(100)
    if mode == "amount":
        return price + value
    return value  # set


def rule_matches(
    rule: PricingRule,
    *,
    plan_id: uuid.UUID,
    room_type_id: uuid.UUID,
    night: date,
    nights: int,
    lead_days: int,
    occupancy: float | None,
) -> bool:
    if rule.room_type_ids and room_type_id not in rule.room_type_ids:
        return False
    if rule.rate_plan_ids and plan_id not in rule.rate_plan_ids:
        return False
    if rule.date_from and night < rule.date_from:
        return False
    if rule.date_to and night > rule.date_to:
        return False
    if rule.weekdays and night.weekday() not in rule.weekdays:
        return False
    c = rule.conditions or {}
    if rule.kind == "occupancy":
        return occupancy is not None and occupancy >= float(c.get("min_occupancy", 101))
    if rule.kind == "long_stay":
        return nights >= int(c.get("min_nights", 10**6))
    if rule.kind == "last_minute":
        return lead_days <= int(c.get("max_days_before", -1))
    if rule.kind == "early_bird":
        return lead_days >= int(c.get("min_days_before", 10**6))
    return True


def _base_rate(
    ctx: PricingContext, stay: Stay, plan: RatePlan, night: date, depth: int = 0
) -> tuple[Decimal, str, list[str]]:
    row = ctx.daily.get((plan.id, stay.room_type.id, night))
    if row is not None and row.price is not None:
        return row.price, "daily_rate", []
    parent = ctx.plans.get(plan.parent_rate_plan_id) if plan.parent_rate_plan_id else None
    if parent is not None and depth < MAX_PLAN_DEPTH and plan.derive_mode and plan.derive_value is not None:
        price, _, applied = _base_rate(ctx, stay, parent, night, depth + 1)
        if plan.derive_mode == "amount_per_person":
            price = price + plan.derive_value * (stay.adults + stay.children)
        else:
            price = _adjust(price, plan.derive_mode, plan.derive_value)
        return price, "derived", applied
    rt = stay.room_type
    price = stay.room.base_price if stay.room and stay.room.base_price is not None else rt.base_price
    applied = []
    for rule in ctx.rules:
        if rule.kind in RATE_RULE_KINDS and rule_matches(
            rule,
            plan_id=plan.id,
            room_type_id=rt.id,
            night=night,
            nights=stay.nights,
            lead_days=(stay.arrival - ctx.today).days,
            occupancy=ctx.occupancy.get((rt.id, night)),
        ):
            price = _adjust(price, rule.adjustment, rule.value)
            applied.append(str(rule.id))
    return price, "base", applied


def supplements(stay: Stay) -> Decimal:
    rt = stay.room_type
    extra_adults = max(0, stay.adults - rt.base_occupancy)
    free_places = max(0, rt.base_occupancy - stay.adults)
    extra_children = max(0, stay.children - free_places)
    return extra_adults * rt.extra_adult_price + extra_children * rt.extra_child_price


def night_price(ctx: PricingContext, stay: Stay, night: date) -> NightPrice:
    plan = ctx.plan(stay.rate_plan_id)
    price, source, applied = _base_rate(ctx, stay, plan, night)
    price += supplements(stay)
    lead = (stay.arrival - ctx.today).days
    for rule in ctx.rules:
        if rule.kind in DISCOUNT_RULE_KINDS and rule_matches(
            rule,
            plan_id=plan.id,
            room_type_id=stay.room_type.id,
            night=night,
            nights=stay.nights,
            lead_days=lead,
            occupancy=None,
        ):
            price = _adjust(price, rule.adjustment, rule.value)
            applied.append(str(rule.id))
    return NightPrice(
        night=night,
        price=round_money(max(price, ZERO), ctx.currency),
        source=source,
        rate_plan_id=plan.id,
        rules=applied,
    )


def base_night_rate(
    ctx: PricingContext, plan: RatePlan, room_type: RoomType, night: date
) -> tuple[Decimal, str]:
    """Rate shown in the pricing grid: standard occupancy, no booking discounts."""
    stay = Stay(room_type, None, night, night + timedelta(days=1), room_type.base_occupancy, 0, plan.id)
    price, source, _ = _base_rate(ctx, stay, plan, night)
    return round_money(max(price, ZERO), ctx.currency), source


def restriction_row(
    ctx: PricingContext, plan: RatePlan, room_type_id: uuid.UUID, day: date
) -> tuple[DailyRate | None, bool]:
    """The grid row governing restrictions, and whether it is inherited."""
    for i, p in enumerate(ctx.chain(plan)):
        row = ctx.daily.get((p.id, room_type_id, day))
        if row is not None and (
            row.closed
            or row.closed_to_arrival
            or row.closed_to_departure
            or row.min_stay is not None
            or row.max_stay is not None
        ):
            return row, i > 0
    return None, False


def restriction_issues(ctx: PricingContext, stay: Stay) -> list[dict[str, Any]]:
    plan = ctx.plan(stay.rate_plan_id)
    rt_id = stay.room_type.id
    issues: list[dict[str, Any]] = []
    if not plan.is_active:
        issues.append({"code": "RATE_PLAN_INACTIVE"})
    if plan.room_type_ids and rt_id not in plan.room_type_ids:
        issues.append({"code": "RATE_PLAN_NOT_FOR_ROOM_TYPE"})
    last_night = stay.departure - timedelta(days=1)
    if (plan.valid_from and stay.arrival < plan.valid_from) or (plan.valid_to and last_night > plan.valid_to):
        issues.append({"code": "RATE_PLAN_NOT_VALID_FOR_DATES"})
    lead = (stay.arrival - ctx.today).days
    if (plan.min_advance_days is not None and lead < plan.min_advance_days) or (
        plan.max_advance_days is not None and lead > plan.max_advance_days
    ):
        issues.append(
            {
                "code": "RATE_PLAN_BOOKING_WINDOW",
                "min_days": plan.min_advance_days,
                "max_days": plan.max_advance_days,
            }
        )
    for night in nights_between(stay.arrival, stay.departure):
        row, _ = restriction_row(ctx, plan, rt_id, night)
        if row is not None and row.closed:
            issues.append({"code": "STOP_SELL", "night": night.isoformat()})
            break
    arrival_row, _ = restriction_row(ctx, plan, rt_id, stay.arrival)
    if arrival_row is not None:
        if arrival_row.min_stay and stay.nights < arrival_row.min_stay:
            issues.append({"code": "MIN_STAY_NOT_MET", "min_stay": arrival_row.min_stay})
        if arrival_row.max_stay and stay.nights > arrival_row.max_stay:
            issues.append({"code": "MAX_STAY_EXCEEDED", "max_stay": arrival_row.max_stay})
        if arrival_row.closed_to_arrival:
            issues.append({"code": "CLOSED_TO_ARRIVAL", "date": stay.arrival.isoformat()})
    departure_row, _ = restriction_row(ctx, plan, rt_id, stay.departure)
    if departure_row is not None and departure_row.closed_to_departure:
        issues.append({"code": "CLOSED_TO_DEPARTURE", "date": stay.departure.isoformat()})
    return issues
