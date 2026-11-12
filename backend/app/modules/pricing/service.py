"""Pricing service: context loading, quotes, taxes, the rate grid, bulk
editing, offers, and management of rate plans, rules and cancellation
policies. All prices come from `engine.night_price()`."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit, crud, events
from app.core.context import HotelContext
from app.core.errors import Conflict, ValidationFailed, field_error, register_constraint
from app.core.money import ZERO, round_money
from app.modules.facilities.models import TaxRate
from app.modules.hotels.models import Hotel
from app.modules.inventory import service as inventory
from app.modules.pricing import engine
from app.modules.pricing.engine import NightPrice, PricingContext, Stay, nights_between
from app.modules.pricing.models import CancellationPolicy, DailyRate, PricingRule, RatePlan
from app.modules.rooms.models import RoomType

register_constraint("uq_rate_plans_hotel_id_code", "RATE_PLAN_CODE_EXISTS", field="code")
register_constraint("uq_cancellation_policies_hotel_id_code", "POLICY_CODE_EXISTS", field="code")
register_constraint("fk_rate_plans_hotel_id_rate_plans", "RATE_PLAN_HAS_CHILDREN")
register_constraint("fk_reservation_rooms_hotel_id_rate_plans", "RATE_PLAN_IN_USE")
register_constraint("fk_rate_plans_hotel_id_cancellation_policies", "POLICY_IN_USE")

__all__ = ["NightPrice", "Stay", "nights_between"]

# --- context & quotes ---------------------------------------------------------


def hotel_today(hotel: Hotel) -> date:
    return datetime.now(ZoneInfo(hotel.timezone)).date()


async def load_context(db: AsyncSession, hotel_id: uuid.UUID, start: date, end: date) -> PricingContext:
    """Everything needed to price nights in [start, end] (end inclusive, so
    closed-to-departure on the departure date can be checked)."""
    hotel = await db.get(Hotel, hotel_id)
    assert hotel is not None
    plans = {p.id: p for p in await db.scalars(select(RatePlan).where(RatePlan.hotel_id == hotel_id))}
    default = next((p for p in plans.values() if p.is_default), None)
    if default is None:
        raise Conflict("NO_DEFAULT_RATE_PLAN", "The hotel has no default rate plan")
    rows = await db.scalars(
        select(DailyRate).where(
            DailyRate.hotel_id == hotel_id, DailyRate.date >= start, DailyRate.date <= end
        )
    )
    rules = list(
        await db.scalars(
            select(PricingRule)
            .where(PricingRule.hotel_id == hotel_id, PricingRule.is_active.is_(True))
            .order_by(PricingRule.priority, PricingRule.created_at)
        )
    )
    ctx = PricingContext(
        hotel_id=hotel_id,
        currency=hotel.currency_code,
        today=hotel_today(hotel),
        plans=plans,
        default_plan=default,
        daily={(r.rate_plan_id, r.room_type_id, r.date): r for r in rows},
        rules=rules,
    )
    if any(r.kind == "occupancy" for r in rules) and end > start:
        for a in await inventory.availability(db, hotel_id, start, end):
            if a.total:
                ctx.occupancy[(a.room_type_id, a.night)] = 100.0 * (a.total - a.available) / a.total
    return ctx


@dataclass
class TaxLine:
    code: str
    name: dict[str, str]
    kind: str
    rate: Decimal
    is_inclusive: bool
    amount: Decimal


@dataclass
class StayQuote:
    nights: list[NightPrice]
    accommodation_total: Decimal
    rate_plan_id: uuid.UUID
    issues: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Quote:
    currency: str
    stays: list[StayQuote]
    accommodation_total: Decimal
    taxes: list[TaxLine] = field(default_factory=list)

    @property
    def tax_added(self) -> Decimal:
        return sum((t.amount for t in self.taxes if not t.is_inclusive), ZERO)

    @property
    def grand_total(self) -> Decimal:
        return self.accommodation_total + self.tax_added


async def active_taxes(db: AsyncSession, hotel_id: uuid.UUID, scope: str) -> list[TaxRate]:
    rows = await db.scalars(
        select(TaxRate)
        .where(
            TaxRate.hotel_id == hotel_id, TaxRate.is_active.is_(True), TaxRate.applies_to.in_((scope, "all"))
        )
        .order_by(TaxRate.sort_order, TaxRate.code)
    )
    return list(rows)


def compute_taxes(
    taxes: list[TaxRate], base: Decimal, room_nights: int, person_nights: int, currency: str
) -> list[TaxLine]:
    """Percent taxes apply to the net base. Inclusive taxes are extracted from
    prices for display and accounting; exclusive taxes are added on top."""
    inclusive_pct = sum((t.rate for t in taxes if t.kind == "percent" and t.is_inclusive), ZERO)
    net = base / (1 + inclusive_pct / 100) if inclusive_pct else base
    lines = []
    for t in taxes:
        if t.kind == "percent":
            amount = net * t.rate / 100
        elif t.kind == "fixed_per_night":
            amount = t.rate * room_nights
        else:
            amount = t.rate * person_nights
        lines.append(TaxLine(t.code, t.name, t.kind, t.rate, t.is_inclusive, round_money(amount, currency)))
    return lines


async def quote(
    db: AsyncSession, hotel_id: uuid.UUID, stays: list[Stay], ctx: PricingContext | None = None
) -> Quote:
    if ctx is None:
        ctx = await load_context(db, hotel_id, min(s.arrival for s in stays), max(s.departure for s in stays))
    stay_quotes = []
    room_nights = person_nights = 0
    for s in stays:
        nights = [engine.night_price(ctx, s, n) for n in nights_between(s.arrival, s.departure)]
        stay_quotes.append(
            StayQuote(
                nights=nights,
                accommodation_total=sum((n.price for n in nights), ZERO),
                rate_plan_id=ctx.plan(s.rate_plan_id).id,
                issues=engine.restriction_issues(ctx, s),
            )
        )
        room_nights += len(nights)
        person_nights += len(nights) * (s.adults + s.children)
    accommodation = sum((q.accommodation_total for q in stay_quotes), ZERO)
    taxes = compute_taxes(
        await active_taxes(db, hotel_id, "accommodation"),
        accommodation,
        room_nights,
        person_nights,
        ctx.currency,
    )
    return Quote(currency=ctx.currency, stays=stay_quotes, accommodation_total=accommodation, taxes=taxes)


# --- offers: every applicable plan for a stay ------------------------------------


async def offers(
    db: AsyncSession,
    hotel_id: uuid.UUID,
    arrival: date,
    departure: date,
    adults: int,
    children: int,
    room_type_id: uuid.UUID | None = None,
) -> list[dict[str, Any]]:
    ctx = await load_context(db, hotel_id, arrival, departure)
    types = list(
        await db.scalars(
            select(RoomType)
            .where(RoomType.hotel_id == hotel_id, RoomType.is_active.is_(True))
            .order_by(RoomType.sort_order, RoomType.code)
        )
    )
    if room_type_id:
        types = [t for t in types if t.id == room_type_id]
    avail: dict[uuid.UUID, int] = {}
    for a in await inventory.availability(db, hotel_id, arrival, departure, [t.id for t in types]):
        avail[a.room_type_id] = min(avail.get(a.room_type_id, 10**6), a.available)
    plans = sorted((p for p in ctx.plans.values() if p.is_active), key=lambda p: (p.sort_order, p.code))
    out = []
    for rt in types:
        fits = (
            adults <= rt.max_adults and children <= rt.max_children and adults + children <= rt.max_occupancy
        )
        for plan in plans:
            if plan.room_type_ids and rt.id not in plan.room_type_ids:
                continue
            stay = Stay(rt, None, arrival, departure, adults, children, plan.id)
            nights = [engine.night_price(ctx, stay, n) for n in nights_between(arrival, departure)]
            total = sum((n.price for n in nights), ZERO)
            issues = engine.restriction_issues(ctx, stay)
            if not fits:
                issues.append(
                    {
                        "code": "OCCUPANCY_EXCEEDED",
                        "max_adults": rt.max_adults,
                        "max_children": rt.max_children,
                        "max_occupancy": rt.max_occupancy,
                    }
                )
            out.append(
                {
                    "room_type_id": rt.id,
                    "rate_plan_id": plan.id,
                    "total": total,
                    "average_night": round_money(total / max(1, len(nights)), ctx.currency),
                    "nights": [
                        {"night": n.night, "price": n.price, "price_source": n.source} for n in nights
                    ],
                    "available": avail.get(rt.id, 0),
                    "issues": issues,
                    "bookable": not issues,
                }
            )
    return out


# --- rate grid -------------------------------------------------------------------


async def grid(
    db: AsyncSession, hotel_id: uuid.UUID, plan_id: uuid.UUID, start: date, end: date
) -> dict[str, Any]:
    """Rows: room categories; cells: base rate (standard occupancy) and
    restrictions for each date in [start, end)."""
    if end <= start or (end - start).days > 93:
        raise ValidationFailed("INVALID_RANGE", params={"max_days": 93})
    ctx = await load_context(db, hotel_id, start, end)
    plan = ctx.plans.get(plan_id)
    if plan is None:
        raise ValidationFailed(
            "RATE_PLAN_NOT_FOUND", fields=[field_error("rate_plan_id", "RATE_PLAN_NOT_FOUND")]
        )
    types = list(
        await db.scalars(
            select(RoomType)
            .where(RoomType.hotel_id == hotel_id, RoomType.is_active.is_(True))
            .order_by(RoomType.sort_order, RoomType.code)
        )
    )
    if plan.room_type_ids:
        types = [t for t in types if t.id in plan.room_type_ids]
    avail = {
        (a.room_type_id, a.night): a.available
        for a in await inventory.availability(db, hotel_id, start, end, [t.id for t in types])
    }
    cells = []
    for rt in types:
        for day in nights_between(start, end):
            price, source = engine.base_night_rate(ctx, plan, rt, day)
            row, inherited = engine.restriction_row(ctx, plan, rt.id, day)
            own = ctx.daily.get((plan.id, rt.id, day))
            cells.append(
                {
                    "room_type_id": rt.id,
                    "date": day,
                    "price": price,
                    "source": source,
                    "explicit": own is not None and own.price is not None,
                    "min_stay": row.min_stay if row else None,
                    "max_stay": row.max_stay if row else None,
                    "closed": bool(row and row.closed),
                    "closed_to_arrival": bool(row and row.closed_to_arrival),
                    "closed_to_departure": bool(row and row.closed_to_departure),
                    "restrictions_inherited": inherited,
                    "available": avail.get((rt.id, day), 0),
                }
            )
    return {
        "rate_plan_id": plan.id,
        "start": start,
        "end": end,
        "room_type_ids": [t.id for t in types],
        "cells": cells,
    }


_RESTRICTION_FIELDS = ("min_stay", "max_stay", "closed", "closed_to_arrival", "closed_to_departure")


async def bulk_update(db: AsyncSession, ctx_h: HotelContext, data: Any) -> int:
    """Apply a price action and/or restriction changes to every matching cell."""
    start, end = data.start, data.end  # inclusive
    days = [
        d
        for d in nights_between(start, end + timedelta(days=1))
        if not data.weekdays or d.weekday() in data.weekdays
    ]
    plans = {
        p.id: p
        for p in await db.scalars(
            select(RatePlan).where(RatePlan.hotel_id == ctx_h.hotel_id, RatePlan.id.in_(data.rate_plan_ids))
        )
    }
    types = {
        t.id: t
        for t in await db.scalars(
            select(RoomType).where(RoomType.hotel_id == ctx_h.hotel_id, RoomType.id.in_(data.room_type_ids))
        )
    }
    if len(plans) != len(set(data.rate_plan_ids)):
        raise ValidationFailed(
            "RATE_PLAN_NOT_FOUND", fields=[field_error("rate_plan_ids", "RATE_PLAN_NOT_FOUND")]
        )
    if len(types) != len(set(data.room_type_ids)):
        raise ValidationFailed(
            "ROOM_TYPE_NOT_FOUND", fields=[field_error("room_type_ids", "ROOM_TYPE_NOT_FOUND")]
        )
    ctx = await load_context(db, ctx_h.hotel_id, start, end)
    existing = {
        (r.rate_plan_id, r.room_type_id, r.date): r
        for r in await db.scalars(
            select(DailyRate).where(
                DailyRate.hotel_id == ctx_h.hotel_id,
                DailyRate.rate_plan_id.in_(plans),
                DailyRate.room_type_id.in_(types),
                DailyRate.date >= start,
                DailyRate.date <= end,
            )
        )
    }
    restriction_changes = (
        {f: getattr(data.restrictions, f) for f in data.restrictions.model_fields_set}
        if data.restrictions
        else {}
    )
    changed = 0
    for pid, plan in plans.items():
        for tid, rt in types.items():
            for day in days:
                key = (pid, tid, day)
                row = existing.get(key)
                if row is None:
                    row = DailyRate(
                        hotel_id=ctx_h.hotel_id,
                        rate_plan_id=pid,
                        room_type_id=tid,
                        date=day,
                        price=None,
                        min_stay=None,
                        max_stay=None,
                        closed=False,
                        closed_to_arrival=False,
                        closed_to_departure=False,
                    )
                before = (row.price, *(getattr(row, f) for f in _RESTRICTION_FIELDS))
                if data.price is not None:
                    mode, value = data.price.mode, data.price.value
                    if mode == "clear":
                        row.price = None
                    elif mode == "set":
                        row.price = value
                    else:
                        current, _ = engine.base_night_rate(ctx, plan, rt, day)
                        row.price = round_money(max(engine._adjust(current, mode, value), ZERO), ctx.currency)
                for f, v in restriction_changes.items():
                    setattr(row, f, bool(v) if f.startswith("closed") else v)
                if row.max_stay is not None and row.min_stay is not None and row.max_stay < row.min_stay:
                    raise ValidationFailed(
                        "MAX_STAY_BELOW_MIN", fields=[field_error("restrictions", "MAX_STAY_BELOW_MIN")]
                    )
                after = (row.price, *(getattr(row, f) for f in _RESTRICTION_FIELDS))
                if after == before:
                    continue
                changed += 1
                empty = (
                    row.price is None
                    and row.min_stay is None
                    and row.max_stay is None
                    and not (row.closed or row.closed_to_arrival or row.closed_to_departure)
                )
                if key in existing:
                    if empty:
                        await db.delete(row)
                elif not empty:
                    db.add(row)
    await db.flush()
    audit.record(
        db,
        ctx_h.actor,
        "rate.bulk_update",
        "rate",
        None,
        hotel_id=ctx_h.hotel_id,
        changes={
            "range": [None, f"{start}..{end}"],
            "weekdays": [None, data.weekdays],
            "rate_plans": [None, sorted(p.code for p in plans.values())],
            "room_types": [None, sorted(t.code for t in types.values())],
            "price": [None, data.price.model_dump(mode="json") if data.price else None],
            "restrictions": [None, {k: v for k, v in restriction_changes.items()}],
            "cells": [None, changed],
        },
    )
    await events.emit(
        db,
        hotel_id=ctx_h.hotel_id,
        entity="rate",
        action="updated",
        actor=ctx_h.actor,
        extra={"cells": changed},
    )
    await db.commit()
    return changed


# --- rate plans ------------------------------------------------------------------

PLAN_FIELDS = (
    "code",
    "name",
    "description",
    "meal_plan",
    "is_refundable",
    "cancellation_policy_id",
    "parent_rate_plan_id",
    "derive_mode",
    "derive_value",
    "room_type_ids",
    "valid_from",
    "valid_to",
    "min_advance_days",
    "max_advance_days",
    "is_default",
    "sort_order",
    "is_active",
)


async def list_plans(db: AsyncSession, hotel_id: uuid.UUID) -> list[RatePlan]:
    return list(
        await db.scalars(
            select(RatePlan).where(RatePlan.hotel_id == hotel_id).order_by(RatePlan.sort_order, RatePlan.code)
        )
    )


async def _validate_plan(db: AsyncSession, ctx: HotelContext, plan: RatePlan) -> None:
    errors = []
    if plan.parent_rate_plan_id:
        if plan.derive_mode is None or plan.derive_value is None:
            errors.append(field_error("derive_mode", "DERIVATION_REQUIRED"))
        # Walk up the chain to refuse cycles.
        seen, current = {plan.id}, plan.parent_rate_plan_id
        while current:
            if current in seen:
                errors.append(field_error("parent_rate_plan_id", "RATE_PLAN_CYCLE"))
                break
            seen.add(current)
            parent = await crud.get_scoped(db, RatePlan, ctx.hotel_id, current, code="RATE_PLAN_NOT_FOUND")
            current = parent.parent_rate_plan_id
    else:
        plan.derive_mode = None
        plan.derive_value = None
    if plan.room_type_ids:
        found = await db.scalar(
            select(func.count()).where(RoomType.hotel_id == ctx.hotel_id, RoomType.id.in_(plan.room_type_ids))
        )
        if found != len(set(plan.room_type_ids)):
            errors.append(field_error("room_type_ids", "ROOM_TYPE_NOT_FOUND"))
    if plan.cancellation_policy_id:
        await crud.get_scoped(
            db, CancellationPolicy, ctx.hotel_id, plan.cancellation_policy_id, code="POLICY_NOT_FOUND"
        )
    if plan.is_default and not plan.is_active:
        errors.append(field_error("is_active", "DEFAULT_PLAN_MUST_BE_ACTIVE"))
    if errors:
        raise ValidationFailed(errors[0]["code"], fields=errors)


async def _unset_other_defaults(db: AsyncSession, hotel_id: uuid.UUID, keep: uuid.UUID) -> None:
    for p in await db.scalars(
        select(RatePlan).where(
            RatePlan.hotel_id == hotel_id, RatePlan.is_default.is_(True), RatePlan.id != keep
        )
    ):
        p.is_default = False
    await db.flush()


async def create_plan(db: AsyncSession, ctx: HotelContext, data: Any) -> RatePlan:
    plan = RatePlan(id=uuid.uuid4(), hotel_id=ctx.hotel_id, version=1, **data.model_dump())
    await _validate_plan(db, ctx, plan)
    if plan.is_default:
        await _unset_other_defaults(db, ctx.hotel_id, plan.id)
    return await crud.create(db, ctx, plan, entity="rate_plan", fields=PLAN_FIELDS)


async def update_plan(db: AsyncSession, ctx: HotelContext, plan_id: uuid.UUID, data: Any) -> RatePlan:
    plan = await crud.get_scoped(db, RatePlan, ctx.hotel_id, plan_id, code="RATE_PLAN_NOT_FOUND")
    crud.check_version(plan, data.version)
    changes = data.model_dump(exclude_unset=True, exclude={"version"})
    if plan.is_default and changes.get("is_default") is False:
        raise ValidationFailed(
            "DEFAULT_PLAN_REQUIRED", fields=[field_error("is_default", "DEFAULT_PLAN_REQUIRED")]
        )
    # Validate the merged result on a transient copy before touching the record.
    probe = RatePlan(id=plan.id, hotel_id=plan.hotel_id, **{**crud.snapshot(plan, PLAN_FIELDS), **changes})
    await _validate_plan(db, ctx, probe)
    if probe.is_default:
        await _unset_other_defaults(db, ctx.hotel_id, plan.id)
    merged = {k: getattr(probe, k) for k in PLAN_FIELDS}
    return await crud.update(
        db, ctx, plan, merged, version=data.version, entity="rate_plan", fields=PLAN_FIELDS
    )


async def delete_plan(db: AsyncSession, ctx: HotelContext, plan_id: uuid.UUID) -> None:
    plan = await crud.get_scoped(db, RatePlan, ctx.hotel_id, plan_id, code="RATE_PLAN_NOT_FOUND")
    if plan.is_default:
        raise Conflict("DEFAULT_PLAN_REQUIRED")
    await crud.delete(db, ctx, plan, entity="rate_plan", fields=PLAN_FIELDS)


# --- pricing rules ---------------------------------------------------------------

RULE_FIELDS = (
    "name",
    "kind",
    "priority",
    "date_from",
    "date_to",
    "weekdays",
    "room_type_ids",
    "rate_plan_ids",
    "adjustment",
    "value",
    "conditions",
    "is_active",
)
REQUIRED_CONDITION = {
    "occupancy": "min_occupancy",
    "long_stay": "min_nights",
    "last_minute": "max_days_before",
    "early_bird": "min_days_before",
}


def _validate_rule(rule: PricingRule) -> None:
    needed = REQUIRED_CONDITION.get(rule.kind)
    if needed and not isinstance((rule.conditions or {}).get(needed), int | float):
        raise ValidationFailed(
            "RULE_CONDITION_REQUIRED",
            params={"condition": needed},
            fields=[field_error("conditions", "RULE_CONDITION_REQUIRED", condition=needed)],
        )
    if rule.kind == "season" and not (rule.date_from and rule.date_to):
        raise ValidationFailed(
            "SEASON_DATES_REQUIRED", fields=[field_error("date_from", "SEASON_DATES_REQUIRED")]
        )
    if rule.kind == "weekday" and not rule.weekdays:
        raise ValidationFailed("WEEKDAYS_REQUIRED", fields=[field_error("weekdays", "WEEKDAYS_REQUIRED")])
    if rule.adjustment == "percent" and rule.value <= -100:
        raise ValidationFailed("DISCOUNT_TOO_LARGE", fields=[field_error("value", "DISCOUNT_TOO_LARGE")])


async def list_rules(db: AsyncSession, hotel_id: uuid.UUID) -> list[PricingRule]:
    return list(
        await db.scalars(
            select(PricingRule)
            .where(PricingRule.hotel_id == hotel_id)
            .order_by(PricingRule.priority, PricingRule.created_at)
        )
    )


async def create_rule(db: AsyncSession, ctx: HotelContext, data: Any) -> PricingRule:
    rule = PricingRule(hotel_id=ctx.hotel_id, version=1, **data.model_dump())
    _validate_rule(rule)
    return await crud.create(db, ctx, rule, entity="pricing_rule", fields=RULE_FIELDS)


async def update_rule(db: AsyncSession, ctx: HotelContext, rule_id: uuid.UUID, data: Any) -> PricingRule:
    rule = await crud.get_scoped(db, PricingRule, ctx.hotel_id, rule_id, code="PRICING_RULE_NOT_FOUND")
    changes = data.model_dump(exclude_unset=True, exclude={"version"})
    probe = PricingRule(**{**crud.snapshot(rule, RULE_FIELDS), **changes})
    _validate_rule(probe)
    return await crud.update(
        db, ctx, rule, changes, version=data.version, entity="pricing_rule", fields=RULE_FIELDS
    )


async def delete_rule(db: AsyncSession, ctx: HotelContext, rule_id: uuid.UUID) -> None:
    rule = await crud.get_scoped(db, PricingRule, ctx.hotel_id, rule_id, code="PRICING_RULE_NOT_FOUND")
    await crud.delete(db, ctx, rule, entity="pricing_rule", fields=RULE_FIELDS)


# --- cancellation policies ---------------------------------------------------------

POLICY_FIELDS = (
    "code",
    "name",
    "description",
    "free_until_days",
    "penalty_kind",
    "penalty_value",
    "no_show_nights",
    "is_active",
)


async def list_policies(db: AsyncSession, hotel_id: uuid.UUID) -> list[CancellationPolicy]:
    return list(
        await db.scalars(
            select(CancellationPolicy)
            .where(CancellationPolicy.hotel_id == hotel_id)
            .order_by(CancellationPolicy.code)
        )
    )


async def create_policy(db: AsyncSession, ctx: HotelContext, data: Any) -> CancellationPolicy:
    obj = CancellationPolicy(hotel_id=ctx.hotel_id, version=1, **data.model_dump())
    return await crud.create(db, ctx, obj, entity="cancellation_policy", fields=POLICY_FIELDS)


async def update_policy(
    db: AsyncSession, ctx: HotelContext, policy_id: uuid.UUID, data: Any
) -> CancellationPolicy:
    obj = await crud.get_scoped(db, CancellationPolicy, ctx.hotel_id, policy_id, code="POLICY_NOT_FOUND")
    changes = data.model_dump(exclude_unset=True, exclude={"version"})
    return await crud.update(
        db, ctx, obj, changes, version=data.version, entity="cancellation_policy", fields=POLICY_FIELDS
    )


async def delete_policy(db: AsyncSession, ctx: HotelContext, policy_id: uuid.UUID) -> None:
    obj = await crud.get_scoped(db, CancellationPolicy, ctx.hotel_id, policy_id, code="POLICY_NOT_FOUND")
    await crud.delete(db, ctx, obj, entity="cancellation_policy", fields=POLICY_FIELDS)


def free_cancellation_until(policy: CancellationPolicy | None, arrival: date) -> date | None:
    if policy is None or policy.free_until_days is None:
        return None
    return arrival - timedelta(days=policy.free_until_days)
