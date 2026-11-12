"""Reservation engine.

Integrity rules enforced here (and, for physical rooms, by the database):
* A physical room can never hold two overlapping occupancies
  (exclusion constraint on room_allocations; violations -> 409 ROOM_UNAVAILABLE).
* A room category can never be oversold by staff without the explicit
  `reservations.overbook` permission (category locks + post-change check).
* Nightly prices are fixed when a night is booked; later rate changes do not
  reprice existing nights.
* Status changes follow a fixed state machine; cancellation and no-show
  release inventory.
* Every change produces a reservation event, an audit record and a real-time
  notification in the same transaction.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import audit, crud, events
from app.core.context import HotelContext
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed, field_error, register_constraint
from app.core.money import ZERO
from app.core.permissions import P
from app.modules.guests import service as guests
from app.modules.guests.models import Guest
from app.modules.hotels.models import Hotel
from app.modules.inventory import service as inventory
from app.modules.pricing import engine as pricing_engine
from app.modules.pricing import service as pricing
from app.modules.reservations.models import (
    OCCUPYING_STATUSES,
    IdempotencyKey,
    Reservation,
    ReservationEvent,
    ReservationNight,
    ReservationRoom,
    RoomAllocation,
    RoomBlock,
)
from app.modules.reservations.schemas import (
    AssignRoomIn,
    BookerOut,
    CalendarItem,
    ChangeDatesIn,
    ReservationIn,
    ReservationOut,
    ReservationRoomOut,
    ReservationUpdate,
    RoomBlockIn,
    StayIn,
)
from app.modules.rooms.models import Room, RoomType

register_constraint("ex_room_allocations_no_overlap", "ROOM_UNAVAILABLE")

TRANSITIONS: dict[str, set[str]] = {
    "pending": {"confirmed", "cancelled", "no_show"},
    "confirmed": {"checked_in", "cancelled", "no_show"},
    "checked_in": {"checked_out"},
    "checked_out": set(),
    "cancelled": set(),
    "no_show": set(),
}
CLOSED = {"checked_out", "cancelled", "no_show"}


# --- helpers -----------------------------------------------------------------


def hotel_today(hotel: Hotel) -> date:
    return datetime.now(ZoneInfo(hotel.timezone)).date()


async def _next_code(db: AsyncSession, hotel_id: uuid.UUID, kind: str = "reservation") -> str:
    n = await db.scalar(
        text(
            "INSERT INTO document_sequences (hotel_id, kind, next_value) VALUES (:h, :k, 2) "
            "ON CONFLICT (hotel_id, kind) DO UPDATE SET next_value = document_sequences.next_value + 1 "
            "RETURNING next_value - 1"
        ),
        {"h": hotel_id, "k": kind},
    )
    return f"R{int(n):06d}"


def _event(db: AsyncSession, ctx: HotelContext, res: Reservation, action: str, **details: Any) -> None:
    db.add(
        ReservationEvent(
            hotel_id=ctx.hotel_id,
            reservation_id=res.id,
            user_id=ctx.actor.user_id,
            source=ctx.actor.source,
            action=action,
            details=audit._jsonable(details),
        )
    )


async def _publish(db: AsyncSession, ctx: HotelContext, res: Reservation, action: str, changes: dict) -> None:
    audit.record(
        db, ctx.actor, f"reservation.{action}", "reservation", res.id, hotel_id=ctx.hotel_id, changes=changes
    )
    await events.emit(
        db,
        hotel_id=ctx.hotel_id,
        entity="reservation",
        action=action,
        entity_id=res.id,
        version=res.version,
        actor=ctx.actor,
    )


async def _load_types(
    db: AsyncSession, hotel_id: uuid.UUID, ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, RoomType]:
    wanted = set(ids)
    found = {
        rt.id: rt
        for rt in await db.scalars(
            select(RoomType).where(RoomType.hotel_id == hotel_id, RoomType.id.in_(wanted))
        )
    }
    if len(found) != len(wanted):
        raise ValidationFailed("ROOM_TYPE_NOT_FOUND", fields=[field_error("rooms", "ROOM_TYPE_NOT_FOUND")])
    return found


async def _load_rooms(
    db: AsyncSession, hotel_id: uuid.UUID, ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, Room]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    found = {
        r.id: r for r in await db.scalars(select(Room).where(Room.hotel_id == hotel_id, Room.id.in_(wanted)))
    }
    if len(found) != len(wanted):
        raise ValidationFailed("ROOM_NOT_FOUND", fields=[field_error("rooms", "ROOM_NOT_FOUND")])
    for r in found.values():
        if not r.is_active:
            raise ValidationFailed("ROOM_INACTIVE", params={"room": r.number})
    return found


def _check_occupancy(rt: RoomType, room: Room | None, adults: int, children: int) -> None:
    capacity = room.max_occupancy if room and room.max_occupancy else rt.max_occupancy
    if adults > rt.max_adults or children > rt.max_children or adults + children > capacity:
        raise ValidationFailed(
            "OCCUPANCY_EXCEEDED",
            "Too many guests for this room",
            params={"max_adults": rt.max_adults, "max_children": rt.max_children, "max_occupancy": capacity},
        )


def _apply_totals(res: Reservation, taxes: list[pricing.TaxLine]) -> None:
    res.accommodation_total = sum((rr.accommodation_total for rr in res.rooms if rr.occupies_inventory), ZERO)
    res.tax_breakdown = [
        {
            "code": t.code,
            "name": t.name,
            "kind": t.kind,
            "rate": str(t.rate),
            "is_inclusive": t.is_inclusive,
            "amount": str(t.amount),
        }
        for t in taxes
    ]
    res.tax_total = sum((t.amount for t in taxes if not t.is_inclusive), ZERO)
    res.grand_total = res.accommodation_total + res.tax_total
    res.adults = sum(rr.adults for rr in res.rooms) or 1
    res.children = sum(rr.children for rr in res.rooms)
    live = [rr for rr in res.rooms if rr.occupies_inventory] or res.rooms
    res.arrival = min(rr.arrival for rr in live)
    res.departure = max(rr.departure for rr in live)


async def _recompute(db: AsyncSession, res: Reservation) -> None:
    live = [rr for rr in res.rooms if rr.occupies_inventory]
    accommodation = sum((rr.accommodation_total for rr in live), ZERO)
    room_nights = sum(len(rr.nights) for rr in live)
    person_nights = sum(len(rr.nights) * (rr.adults + rr.children) for rr in live)
    taxes = pricing.compute_taxes(
        await pricing.active_taxes(db, res.hotel_id, "accommodation"),
        accommodation,
        room_nights,
        person_nights,
        res.currency,
    )
    _apply_totals(res, taxes)


def _touch(res: Reservation) -> None:
    """Force a version bump when only child rows changed."""
    res.updated_at = datetime.now(UTC)


async def get_reservation(
    db: AsyncSession, hotel_id: uuid.UUID, res_id: uuid.UUID, *, for_update: bool = False
) -> Reservation:
    return await crud.get_scoped(
        db, Reservation, hotel_id, res_id, code="RESERVATION_NOT_FOUND", for_update=for_update
    )


async def reservation_out(db: AsyncSession, res: Reservation) -> ReservationOut:
    guest = await db.get(Guest, res.booker_guest_id)
    modified = await db.scalar(
        select(func.count())
        .select_from(ReservationEvent)
        .where(
            ReservationEvent.reservation_id == res.id,
            ReservationEvent.action.in_(("dates_changed", "room_assigned", "details_updated")),
        )
    )
    return ReservationOut(
        **{
            f: getattr(res, f)
            for f in (
                "id",
                "code",
                "status",
                "source",
                "external_ref",
                "arrival",
                "departure",
                "adults",
                "children",
                "currency",
                "accommodation_total",
                "tax_total",
                "grand_total",
                "paid_total",
                "tax_breakdown",
                "is_overbooked",
                "special_requests",
                "internal_notes",
                "cancelled_at",
                "cancellation_reason",
                "version",
                "created_at",
                "updated_at",
            )
        },
        balance=res.grand_total - res.paid_total,
        is_modified=bool(modified),
        booker=BookerOut.model_validate(guest),
        rooms=[ReservationRoomOut.model_validate(rr) for rr in res.rooms],
    )


async def reload(db: AsyncSession, res: Reservation) -> Reservation:
    """Re-read a reservation with its rooms and nights after a commit
    (async sessions cannot lazy-load nested collections)."""
    stmt = (
        select(Reservation)
        .where(Reservation.id == res.id)
        .options(selectinload(Reservation.rooms).selectinload(ReservationRoom.nights))
        .execution_options(populate_existing=True)
    )
    return (await db.scalars(stmt)).one()


# --- quote -------------------------------------------------------------------


async def _stay_requests(
    db: AsyncSession, hotel_id: uuid.UUID, arrival: date, departure: date, stays: list[StayIn]
) -> list[pricing_engine.Stay]:
    types = await _load_types(db, hotel_id, [s.room_type_id for s in stays])
    rooms = await _load_rooms(db, hotel_id, [s.room_id for s in stays])
    requests = []
    for s in stays:
        rt = types[s.room_type_id]
        if not rt.is_active:
            raise ValidationFailed("ROOM_TYPE_INACTIVE")
        room = rooms.get(s.room_id) if s.room_id else None
        _check_occupancy(rt, room, s.adults, s.children)
        requests.append(
            pricing_engine.Stay(
                room_type=rt,
                room=room,
                arrival=s.arrival or arrival,
                departure=s.departure or departure,
                adults=s.adults,
                children=s.children,
                rate_plan_id=s.rate_plan_id,
            )
        )
    return requests


def _check_plans(pctx: pricing_engine.PricingContext, stays: list[pricing_engine.Stay]) -> None:
    for s in stays:
        if s.rate_plan_id and s.rate_plan_id not in pctx.plans:
            raise ValidationFailed(
                "RATE_PLAN_NOT_FOUND", fields=[field_error("rooms", "RATE_PLAN_NOT_FOUND")]
            )


def _enforce_restrictions(ctx: HotelContext, q: pricing.Quote, override: bool) -> list[str]:
    """Stay restrictions (stop sell, min/max stay, CTA/CTD, plan conditions)
    block a booking unless explicitly overridden by an authorised user."""
    issues = [i for stay in q.stays for i in stay.issues]
    if not issues:
        return []
    if not override:
        first = issues[0]
        raise Conflict(first["code"], first["code"], params={k: v for k, v in first.items() if k != "code"})
    if not ctx.has(P.RESERVATIONS_OVERRIDE):
        raise Forbidden("PERMISSION_DENIED", params={"permission": P.RESERVATIONS_OVERRIDE})
    return sorted({i["code"] for i in issues})


async def quote(
    db: AsyncSession, ctx: HotelContext, arrival: date, departure: date, stays: list[StayIn]
) -> pricing.Quote:
    requests = await _stay_requests(db, ctx.hotel_id, arrival, departure, stays)
    pctx = await pricing.load_context(
        db, ctx.hotel_id, min(r.arrival for r in requests), max(r.departure for r in requests)
    )
    _check_plans(pctx, requests)
    return await pricing.quote(db, ctx.hotel_id, requests, pctx)


# --- create ------------------------------------------------------------------


def _payload_hash(data: ReservationIn) -> str:
    return hashlib.sha256(json.dumps(data.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()


async def _replay(db: AsyncSession, ctx: HotelContext, key: str, digest: str) -> Reservation | None:
    row = await db.get(IdempotencyKey, (ctx.hotel_id, ctx.actor.user_id, key))
    if row is None:
        return None
    if row.request_hash != digest:
        raise Conflict("IDEMPOTENCY_KEY_REUSED", "This Idempotency-Key was used for a different request")
    return await get_reservation(db, ctx.hotel_id, row.resource_id)


async def create_reservation(
    db: AsyncSession, ctx: HotelContext, data: ReservationIn, idempotency_key: str | None = None
) -> tuple[Reservation, bool]:
    """Returns (reservation, created). created=False when an idempotent retry
    returned the reservation made by the first attempt."""
    digest = _payload_hash(data)
    if idempotency_key:
        existing = await _replay(db, ctx, idempotency_key, digest)
        if existing:
            return existing, False
    if data.allow_overbooking and not ctx.has(P.RESERVATIONS_OVERBOOK):
        raise Forbidden("PERMISSION_DENIED", params={"permission": P.RESERVATIONS_OVERBOOK})

    hotel = await db.get(Hotel, ctx.hotel_id)
    assert hotel is not None
    requests = await _stay_requests(db, ctx.hotel_id, data.arrival, data.departure, data.rooms)
    affected_types = {r.room_type.id for r in requests} | {r.room.room_type_id for r in requests if r.room}
    start = min(r.arrival for r in requests)
    end = max(r.departure for r in requests)

    if idempotency_key:
        # Claim the key first: a concurrent retry blocks here until we commit,
        # then fails on the primary key and replays our result.
        db.add(
            IdempotencyKey(
                hotel_id=ctx.hotel_id,
                user_id=ctx.actor.user_id,
                key=idempotency_key,
                request_hash=digest,
                resource_id=uuid.uuid4(),
            )
        )
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            existing = await _replay(db, ctx, idempotency_key, digest)
            if existing:
                return existing, False
            raise

    if data.guest_id:
        guest = await crud.get_scoped(db, Guest, ctx.hotel_id, data.guest_id, code="GUEST_NOT_FOUND")
    else:
        assert data.guest is not None
        guest = await guests.create_guest(db, ctx, data.guest, commit=False)

    pctx = await pricing.load_context(db, ctx.hotel_id, start, end)
    _check_plans(pctx, requests)
    q = await pricing.quote(db, ctx.hotel_id, requests, pctx)
    overridden = _enforce_restrictions(ctx, q, data.override_restrictions)
    await inventory.lock_room_types(db, ctx.hotel_id, affected_types)

    res = Reservation(
        id=uuid.uuid4(),
        hotel_id=ctx.hotel_id,
        code=await _next_code(db, ctx.hotel_id),
        booker_guest_id=guest.id,
        status=data.status,
        source=data.source,
        external_ref=data.external_ref,
        arrival=start,
        departure=end,
        adults=1,
        children=0,
        currency=hotel.currency_code,
        special_requests=data.special_requests,
        internal_notes=data.internal_notes,
        created_by=ctx.actor.user_id,
        version=1,
    )
    res.rooms = []
    for r, sq in zip(requests, q.stays, strict=True):
        rr = ReservationRoom(
            id=uuid.uuid4(),
            hotel_id=ctx.hotel_id,
            room_type_id=r.room_type.id,
            room_id=r.room.id if r.room else None,
            rate_plan_id=sq.rate_plan_id,
            arrival=r.arrival,
            departure=r.departure,
            adults=r.adults,
            children=r.children,
            occupies_inventory=True,
            accommodation_total=sq.accommodation_total,
        )
        rr.nights = [
            ReservationNight(
                night=n.night,
                hotel_id=ctx.hotel_id,
                price=n.price,
                price_source=n.source,
                rate_plan_id=n.rate_plan_id,
            )
            for n in sq.nights
        ]
        res.rooms.append(rr)
    _apply_totals(res, q.taxes)
    db.add(res)
    await db.flush()  # room_allocations trigger + exclusion constraint run here

    short = await inventory.oversold_nights(db, ctx.hotel_id, affected_types, start, end)
    if short:
        if not data.allow_overbooking:
            raise Conflict(
                "NO_AVAILABILITY",
                "Not enough rooms available in this category",
                params={"night": short[0].night.isoformat(), "room_type_id": str(short[0].room_type_id)},
            )
        res.is_overbooked = True

    if idempotency_key:
        key_row = await db.get(IdempotencyKey, (ctx.hotel_id, ctx.actor.user_id, idempotency_key))
        assert key_row is not None
        key_row.resource_id = res.id

    _event(
        db,
        ctx,
        res,
        "created",
        status=res.status,
        source=res.source,
        rooms=len(res.rooms),
        overbooked=res.is_overbooked,
        restrictions_overridden=overridden,
    )
    await _publish(
        db,
        ctx,
        res,
        "created",
        {
            "code": [None, res.code],
            "status": [None, res.status],
            "arrival": [None, res.arrival],
            "departure": [None, res.departure],
        },
    )
    await db.commit()
    return res, True


# --- modify ------------------------------------------------------------------


async def update_details(
    db: AsyncSession, ctx: HotelContext, res_id: uuid.UUID, data: ReservationUpdate
) -> Reservation:
    res = await get_reservation(db, ctx.hotel_id, res_id)
    crud.check_version(res, data.version)
    changes = data.model_dump(exclude_unset=True, exclude={"version"})
    if "source" in changes and changes["source"] is None:
        raise ValidationFailed(fields=[field_error("source", "REQUIRED")])
    before = {k: getattr(res, k) for k in changes}
    for k, v in changes.items():
        setattr(res, k, v)
    delta = audit.diff(before, {k: getattr(res, k) for k in changes})
    if delta:
        await db.flush()
        _event(db, ctx, res, "details_updated", fields=sorted(delta))
        await _publish(db, ctx, res, "updated", delta)
        await db.commit()
        return await reload(db, res)


def _find_room(res: Reservation, rr_id: uuid.UUID) -> ReservationRoom:
    for rr in res.rooms:
        if rr.id == rr_id:
            return rr
    raise NotFound("RESERVATION_ROOM_NOT_FOUND")


_UNSET: Any = object()


async def move_stay(
    db: AsyncSession,
    ctx: HotelContext,
    res_id: uuid.UUID,
    rr_id: uuid.UUID,
    *,
    version: int,
    room_id: uuid.UUID | None = _UNSET,
    arrival: date | None = None,
    departure: date | None = None,
) -> Reservation:
    """Change the room and/or the dates of one stay in a single transaction.

    Used by room assignment, date changes and calendar drag-and-drop. Nights
    that remain booked keep their price; only new nights are priced at
    current rates. The exclusion constraint and the category check guarantee
    the result never double-allocates or oversells.
    """
    res = await get_reservation(db, ctx.hotel_id, res_id)
    crud.check_version(res, version)
    if res.status in CLOSED:
        raise Conflict("RESERVATION_CLOSED", params={"status": res.status})
    rr = _find_room(res, rr_id)
    new_room_id = rr.room_id if room_id is _UNSET else room_id
    new_arrival = arrival or rr.arrival
    new_departure = departure or rr.departure
    if new_departure <= new_arrival:
        raise ValidationFailed("INVALID_DATES", fields=[field_error("departure", "INVALID_DATES")])
    room_changed = new_room_id != rr.room_id
    dates_changed = (new_arrival, new_departure) != (rr.arrival, rr.departure)
    if not room_changed and not dates_changed:
        return res
    if rr.checked_in_at and room_changed:
        # Moving an in-house guest is a room move with its own workflow (front desk).
        raise Conflict("GUEST_IN_HOUSE")
    if rr.checked_in_at and new_arrival != rr.arrival:
        raise Conflict("ARRIVAL_LOCKED_AFTER_CHECK_IN")

    hotel = await db.get(Hotel, ctx.hotel_id)
    rt = await db.get(RoomType, rr.room_type_id)
    assert hotel is not None and rt is not None
    old_room = await db.get(Room, rr.room_id) if rr.room_id else None
    new_room = (await _load_rooms(db, ctx.hotel_id, [new_room_id]))[new_room_id] if new_room_id else None
    if room_changed and new_room:
        _check_occupancy(rt, new_room, rr.adults, rr.children)
    affected = {rr.room_type_id} | {r.room_type_id for r in (old_room, new_room) if r}
    await inventory.lock_room_types(db, ctx.hotel_id, affected)

    old_dates = (rr.arrival, rr.departure)
    if dates_changed:
        kept = {n.night: n for n in rr.nights}
        pctx = await pricing.load_context(db, ctx.hotel_id, new_arrival, new_departure)
        stay = pricing_engine.Stay(
            rt, new_room, new_arrival, new_departure, rr.adults, rr.children, rr.rate_plan_id
        )
        nights = []
        for night in pricing_engine.nights_between(new_arrival, new_departure):
            if night in kept:
                nights.append(kept[night])
            else:
                p = pricing_engine.night_price(pctx, stay, night)
                nights.append(
                    ReservationNight(
                        night=night,
                        hotel_id=ctx.hotel_id,
                        price=p.price,
                        price_source=p.source,
                        rate_plan_id=p.rate_plan_id,
                    )
                )
        rr.nights = nights
        rr.arrival, rr.departure = new_arrival, new_departure
        rr.accommodation_total = sum((n.price for n in nights), ZERO)
        await _recompute(db, res)
    if room_changed:
        rr.room_id = new_room_id
    _touch(res)
    await db.flush()  # exclusion constraint on the allocation ledger
    window = (min(old_dates[0], new_arrival), max(old_dates[1], new_departure))
    short = await inventory.oversold_nights(db, ctx.hotel_id, affected, *window)
    if short and not res.is_overbooked:
        raise Conflict(
            "NO_AVAILABILITY",
            params={"night": short[0].night.isoformat(), "room_type_id": str(short[0].room_type_id)},
        )
    changes: dict[str, Any] = {}
    if room_changed:
        old_no, new_no = (old_room.number if old_room else None), (new_room.number if new_room else None)
        _event(db, ctx, res, "room_assigned", reservation_room_id=rr.id, old_room=old_no, new_room=new_no)
        changes["room"] = [old_no, new_no]
    if dates_changed:
        _event(
            db,
            ctx,
            res,
            "dates_changed",
            reservation_room_id=rr.id,
            old=list(old_dates),
            new=[new_arrival, new_departure],
        )
        changes["dates"] = [list(old_dates), [new_arrival, new_departure]]
    await _publish(db, ctx, res, "updated", changes)
    await db.commit()
    return await reload(db, res)


async def change_rate_plan(
    db: AsyncSession,
    ctx: HotelContext,
    res_id: uuid.UUID,
    rr_id: uuid.UUID,
    *,
    version: int,
    rate_plan_id: uuid.UUID,
    override_restrictions: bool = False,
) -> Reservation:
    """Switch a stay to another rate plan (e.g. the guest adds breakfast).
    Every night is repriced at the new plan's current rates."""
    res = await get_reservation(db, ctx.hotel_id, res_id)
    crud.check_version(res, version)
    if res.status in CLOSED:
        raise Conflict("RESERVATION_CLOSED", params={"status": res.status})
    rr = _find_room(res, rr_id)
    if rr.rate_plan_id == rate_plan_id:
        return res
    rt = await db.get(RoomType, rr.room_type_id)
    room = await db.get(Room, rr.room_id) if rr.room_id else None
    assert rt is not None
    pctx = await pricing.load_context(db, ctx.hotel_id, rr.arrival, rr.departure)
    if rate_plan_id not in pctx.plans:
        raise ValidationFailed(
            "RATE_PLAN_NOT_FOUND", fields=[field_error("rate_plan_id", "RATE_PLAN_NOT_FOUND")]
        )
    stay = pricing_engine.Stay(rt, room, rr.arrival, rr.departure, rr.adults, rr.children, rate_plan_id)
    issues = pricing_engine.restriction_issues(pctx, stay)
    overridden = _enforce_restrictions(
        ctx,
        pricing.Quote(
            currency=res.currency,
            stays=[pricing.StayQuote([], ZERO, rate_plan_id, issues)],
            accommodation_total=ZERO,
        ),
        override_restrictions,
    )
    old_plan, old_total = rr.rate_plan_id, rr.accommodation_total
    prices = [pricing_engine.night_price(pctx, stay, n.night) for n in rr.nights]
    by_night = {p.night: p for p in prices}
    for n in rr.nights:
        p = by_night[n.night]
        n.price, n.price_source, n.rate_plan_id = p.price, p.source, p.rate_plan_id
    rr.rate_plan_id = rate_plan_id
    rr.accommodation_total = sum((p.price for p in prices), ZERO)
    await _recompute(db, res)
    _touch(res)
    await db.flush()
    names = {pid: pctx.plans[pid].code for pid in (old_plan, rate_plan_id) if pid in pctx.plans}
    _event(
        db,
        ctx,
        res,
        "rate_plan_changed",
        reservation_room_id=rr.id,
        old=names.get(old_plan),
        new=names.get(rate_plan_id),
        old_total=old_total,
        new_total=rr.accommodation_total,
        restrictions_overridden=overridden,
    )
    await _publish(db, ctx, res, "updated", {"rate_plan": [names.get(old_plan), names.get(rate_plan_id)]})
    await db.commit()
    return await reload(db, res)


async def assign_room(
    db: AsyncSession, ctx: HotelContext, res_id: uuid.UUID, rr_id: uuid.UUID, data: AssignRoomIn
) -> Reservation:
    return await move_stay(db, ctx, res_id, rr_id, version=data.version, room_id=data.room_id)


async def change_dates(
    db: AsyncSession, ctx: HotelContext, res_id: uuid.UUID, rr_id: uuid.UUID, data: ChangeDatesIn
) -> Reservation:
    return await move_stay(
        db, ctx, res_id, rr_id, version=data.version, arrival=data.arrival, departure=data.departure
    )


async def available_rooms(
    db: AsyncSession,
    hotel_id: uuid.UUID,
    start: date,
    end: date,
    *,
    room_type_id: uuid.UUID | None = None,
    ignore_reservation_room: uuid.UUID | None = None,
) -> list[Room]:
    """Active rooms with no allocation overlapping [start, end). The stay being
    edited can be ignored so its own room is offered as available."""
    busy = select(RoomAllocation.room_id).where(
        RoomAllocation.hotel_id == hotel_id,
        RoomAllocation.period.op("&&")(func.daterange(start, end, "[)")),
    )
    if ignore_reservation_room:
        busy = busy.where(
            or_(
                RoomAllocation.reservation_room_id.is_(None),
                RoomAllocation.reservation_room_id != ignore_reservation_room,
            )
        )
    stmt = select(Room).where(Room.hotel_id == hotel_id, Room.is_active.is_(True), Room.id.not_in(busy))
    if room_type_id:
        stmt = stmt.where(Room.room_type_id == room_type_id)
    stmt = stmt.order_by(Room.sort_order, func.length(Room.number), Room.number)
    return list(await db.scalars(stmt))


async def _transition(
    db: AsyncSession, ctx: HotelContext, res: Reservation, new: str, **details: Any
) -> None:
    if new not in TRANSITIONS[res.status]:
        raise Conflict("INVALID_STATUS_TRANSITION", params={"from": res.status, "to": new})
    old = res.status
    res.status = new
    occupying = new in OCCUPYING_STATUSES
    for rr in res.rooms:
        rr.occupies_inventory = occupying
    if not occupying:
        await _recompute(db, res)
    _event(db, ctx, res, "status_changed", **{"from": old, "to": new}, **details)
    await db.flush()
    await _publish(db, ctx, res, "updated", {"status": [old, new]})


async def confirm(db: AsyncSession, ctx: HotelContext, res_id: uuid.UUID, version: int) -> Reservation:
    res = await get_reservation(db, ctx.hotel_id, res_id)
    crud.check_version(res, version)
    await _transition(db, ctx, res, "confirmed")
    await db.commit()
    return await reload(db, res)


async def cancel(
    db: AsyncSession, ctx: HotelContext, res_id: uuid.UUID, version: int, reason: str
) -> Reservation:
    res = await get_reservation(db, ctx.hotel_id, res_id)
    crud.check_version(res, version)
    res.cancelled_at = datetime.now(UTC)
    res.cancellation_reason = reason
    await _transition(db, ctx, res, "cancelled", reason=reason)
    await db.commit()
    return await reload(db, res)


async def mark_no_show(db: AsyncSession, ctx: HotelContext, res_id: uuid.UUID, version: int) -> Reservation:
    res = await get_reservation(db, ctx.hotel_id, res_id)
    crud.check_version(res, version)
    hotel = await db.get(Hotel, ctx.hotel_id)
    assert hotel is not None
    if hotel_today(hotel) < res.arrival:
        raise Conflict("NO_SHOW_BEFORE_ARRIVAL")
    await _transition(db, ctx, res, "no_show")
    await db.commit()
    return await reload(db, res)


# --- queries -----------------------------------------------------------------


async def list_reservations(
    db: AsyncSession,
    ctx: HotelContext,
    *,
    start: date | None,
    end: date | None,
    status: str | None,
    q: str | None,
    limit: int,
    offset: int,
    guest_id: uuid.UUID | None = None,
    arrival: date | None = None,
    departure: date | None = None,
) -> tuple[list[dict[str, Any]], int]:
    stmt = (
        select(Reservation, Guest)
        .join(Guest, Guest.id == Reservation.booker_guest_id)
        .where(Reservation.hotel_id == ctx.hotel_id)
    )
    if start:
        stmt = stmt.where(Reservation.departure > start)
    if end:
        stmt = stmt.where(Reservation.arrival < end)
    if status:
        stmt = stmt.where(Reservation.status == status)
    if guest_id:
        stmt = stmt.where(Reservation.booker_guest_id == guest_id)
    if arrival:
        stmt = stmt.where(Reservation.arrival == arrival)
    if departure:
        stmt = stmt.where(Reservation.departure == departure)
    if q and q.strip():
        term = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Reservation.code.ilike(term),
                Reservation.external_ref.ilike(term),
                (Guest.first_name + " " + Guest.last_name).ilike(term),
                Guest.email.ilike(term),
            )
        )
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (
        await db.execute(stmt.order_by(Reservation.arrival, Reservation.code).limit(limit).offset(offset))
    ).all()
    room_ids = {rr.room_id for res, _ in rows for rr in res.rooms if rr.room_id}
    numbers = (
        {r.id: r.number for r in await db.scalars(select(Room).where(Room.id.in_(room_ids)))}
        if room_ids
        else {}
    )
    items = [
        {
            "id": res.id,
            "code": res.code,
            "status": res.status,
            "source": res.source,
            "arrival": res.arrival,
            "departure": res.departure,
            "adults": res.adults,
            "children": res.children,
            "guest_name": f"{g.first_name} {g.last_name}",
            "room_numbers": sorted(numbers[rr.room_id] for rr in res.rooms if rr.room_id),
            "room_count": len(res.rooms),
            "grand_total": res.grand_total,
            "balance": res.grand_total - res.paid_total,
            "currency": res.currency,
            "is_overbooked": res.is_overbooked,
        }
        for res, g in rows
    ]
    return items, int(total or 0)


async def reservation_events(db: AsyncSession, ctx: HotelContext, res_id: uuid.UUID) -> list[dict[str, Any]]:
    """History with staff names (visible to anyone who can view the reservation)."""
    from app.modules.auth.models import User

    await get_reservation(db, ctx.hotel_id, res_id)
    rows = await db.execute(
        select(ReservationEvent, User.full_name)
        .outerjoin(User, User.id == ReservationEvent.user_id)
        .where(ReservationEvent.reservation_id == res_id)
        .order_by(ReservationEvent.id)
    )
    return [
        {
            "id": e.id,
            "at": e.at,
            "user_id": e.user_id,
            "user_name": name,
            "source": e.source,
            "action": e.action,
            "details": e.details,
        }
        for e, name in rows
    ]


async def calendar(db: AsyncSession, ctx: HotelContext, start: date, end: date) -> dict[str, Any]:
    if (end - start).days > 93 or end <= start:
        raise ValidationFailed("INVALID_RANGE", params={"max_days": 93})
    rng = func.daterange(start, end, "[)")
    stays = await db.execute(
        select(ReservationRoom, Reservation, Guest)
        .join(Reservation, Reservation.id == ReservationRoom.reservation_id)
        .join(Guest, Guest.id == Reservation.booker_guest_id)
        .where(
            ReservationRoom.hotel_id == ctx.hotel_id,
            ReservationRoom.occupies_inventory.is_(True),
            ReservationRoom.stay.op("&&")(rng),
        )
    )
    items, unassigned = [], []
    for rr, res, g in stays:
        item = CalendarItem(
            kind="stay",
            id=rr.id,
            room_id=rr.room_id,
            room_type_id=rr.room_type_id,
            start=rr.arrival,
            end=rr.departure,
            reservation_id=res.id,
            code=res.code,
            guest_name=f"{g.first_name} {g.last_name}",
            status=res.status,
            adults=rr.adults,
            children=rr.children,
        )
        (items if rr.room_id else unassigned).append(item)
    blocks = await db.scalars(
        select(RoomBlock).where(
            RoomBlock.hotel_id == ctx.hotel_id, RoomBlock.start_date < end, RoomBlock.end_date > start
        )
    )
    for b in blocks:
        items.append(
            CalendarItem(
                kind="block",
                id=b.id,
                room_id=b.room_id,
                start=b.start_date,
                end=b.end_date,
                block_reason=b.reason,
            )
        )
    return {
        "start": start,
        "end": end,
        "items": items,
        "unassigned": unassigned,
        "availability": await availability_out(db, ctx.hotel_id, start, end),
    }


async def availability_out(
    db: AsyncSession, hotel_id: uuid.UUID, start: date, end: date, room_type_id: uuid.UUID | None = None
) -> list[dict[str, Any]]:
    rows = await inventory.availability(db, hotel_id, start, end, [room_type_id] if room_type_id else None)
    grouped: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for r in rows:
        grouped.setdefault(r.room_type_id, []).append(
            {"night": r.night, "total": r.total, "available": r.available}
        )
    return [{"room_type_id": k, "nights": v} for k, v in grouped.items()]


# --- room blocks -------------------------------------------------------------


async def create_block(db: AsyncSession, ctx: HotelContext, data: RoomBlockIn) -> RoomBlock:
    room = (await _load_rooms(db, ctx.hotel_id, [data.room_id]))[data.room_id]
    await inventory.lock_room_types(db, ctx.hotel_id, [room.room_type_id])
    block = RoomBlock(
        hotel_id=ctx.hotel_id,
        room_id=room.id,
        start_date=data.start_date,
        end_date=data.end_date,
        reason=data.reason,
        notes=data.notes,
        created_by=ctx.actor.user_id,
    )
    db.add(block)
    await db.flush()  # exclusion constraint vs. stays and other blocks
    short = await inventory.oversold_nights(
        db, ctx.hotel_id, [room.room_type_id], data.start_date, data.end_date
    )
    if short:
        raise Conflict(
            "NO_AVAILABILITY",
            params={"night": short[0].night.isoformat(), "room_type_id": str(room.room_type_id)},
        )
    audit.record(
        db,
        ctx.actor,
        "room_block.create",
        "room_block",
        block.id,
        hotel_id=ctx.hotel_id,
        changes=audit.diff(
            None, {"room": room.number, "start": data.start_date, "end": data.end_date, "reason": data.reason}
        ),
    )
    await events.emit(
        db, hotel_id=ctx.hotel_id, entity="room_block", action="created", entity_id=block.id, actor=ctx.actor
    )
    await db.commit()
    return block


async def delete_block(db: AsyncSession, ctx: HotelContext, block_id: uuid.UUID) -> None:
    block = await crud.get_scoped(db, RoomBlock, ctx.hotel_id, block_id, code="ROOM_BLOCK_NOT_FOUND")
    await db.delete(block)
    audit.record(db, ctx.actor, "room_block.delete", "room_block", block_id, hotel_id=ctx.hotel_id)
    await events.emit(
        db, hotel_id=ctx.hotel_id, entity="room_block", action="deleted", entity_id=block_id, actor=ctx.actor
    )
    await db.commit()


async def allocation_count(db: AsyncSession, hotel_id: uuid.UUID) -> int:
    return int(
        await db.scalar(
            select(func.count()).select_from(RoomAllocation).where(RoomAllocation.hotel_id == hotel_id)
        )
        or 0
    )
