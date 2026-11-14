"""Front desk: check-in, check-out, in-house room moves and the daily views.

Rules:
* Check-in: from the arrival date (late arrivals allowed) until the night
  before departure; every stay needs an assigned room; the room must be
  vacated by the previous guest; a room not yet clean needs explicit
  confirmation.
* Check-out: the reservation's balance must be settled when its last room
  leaves (an open balance needs confirmation, and folio.adjust when the
  guest still owes money). Leaving early releases the unused nights.
* Checked-out rooms become dirty for housekeeping.
* An in-house room move splits the stay at today's date: past nights stay
  on the old room, the remaining nights move with their booked prices.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crud
from app.core.context import HotelContext
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.money import ZERO
from app.core.permissions import P
from app.modules.billing import folio
from app.modules.billing.service import hotel_today, load_reservation
from app.modules.guests.models import Guest
from app.modules.hotels.models import Hotel
from app.modules.housekeeping import service as housekeeping
from app.modules.housekeeping.status import after_departure
from app.modules.inventory import service as inventory
from app.modules.maintenance import service as maintenance_service
from app.modules.reservations.history import event, publish
from app.modules.reservations.models import (
    OCCUPYING_STATUSES,
    Reservation,
    ReservationNight,
    ReservationRoom,
    RoomBlock,
)
from app.modules.reservations.service import TRANSITIONS, _check_occupancy
from app.modules.rooms.models import Room, RoomType

NOT_READY = ("dirty", "in_progress")


async def _hotel(db: AsyncSession, hotel_id: uuid.UUID) -> Hotel:
    hotel = await db.get(Hotel, hotel_id)
    assert hotel is not None
    return hotel


def _touch(res: Reservation) -> None:
    res.updated_at = datetime.now(UTC)


def _select_stays(
    res: Reservation, ids: list[uuid.UUID] | None, eligible: list[ReservationRoom]
) -> list[ReservationRoom]:
    if ids is None:
        return eligible
    by_id = {rr.id: rr for rr in res.rooms}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise NotFound("RESERVATION_ROOM_NOT_FOUND")
    return [by_id[i] for i in dict.fromkeys(ids)]


async def _occupant(db: AsyncSession, room_id: uuid.UUID, exclude: uuid.UUID) -> Reservation | None:
    """Reservation whose guest is currently in this room (checked in, not out)."""
    row = (
        await db.execute(
            select(Reservation)
            .join(ReservationRoom, ReservationRoom.reservation_id == Reservation.id)
            .where(
                ReservationRoom.room_id == room_id,
                ReservationRoom.id != exclude,
                ReservationRoom.checked_in_at.is_not(None),
                ReservationRoom.checked_out_at.is_(None),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return row


# --- check-in -----------------------------------------------------------------------


async def check_in(
    db: AsyncSession,
    ctx: HotelContext,
    res_id: uuid.UUID,
    *,
    version: int,
    reservation_room_ids: list[uuid.UUID] | None,
    ignore_room_status: bool,
) -> Reservation:
    res = await load_reservation(db, ctx.hotel_id, res_id, for_update=True)
    crud.check_version(res, version)
    if res.status != "checked_in" and "checked_in" not in TRANSITIONS[res.status]:
        raise Conflict("INVALID_STATUS_TRANSITION", params={"from": res.status, "to": "checked_in"})
    hotel = await _hotel(db, ctx.hotel_id)
    today = hotel_today(hotel)
    waiting = [rr for rr in res.rooms if rr.occupies_inventory and rr.checked_in_at is None]
    if reservation_room_ids is None:
        targets = [rr for rr in waiting if rr.arrival <= today < rr.departure]
        if not targets:
            future = [rr for rr in waiting if rr.arrival > today]
            if future:
                raise Conflict(
                    "CHECK_IN_TOO_EARLY", params={"arrival": min(r.arrival for r in future).isoformat()}
                )
            raise Conflict("NOTHING_TO_CHECK_IN")
    else:
        targets = _select_stays(res, reservation_room_ids, waiting)
    for rr in targets:
        if rr.checked_in_at is not None:
            raise Conflict("ALREADY_CHECKED_IN")
        if rr.arrival > today:
            raise Conflict("CHECK_IN_TOO_EARLY", params={"arrival": rr.arrival.isoformat()})
        if rr.departure <= today:
            raise Conflict("STAY_ALREADY_ENDED", params={"departure": rr.departure.isoformat()})
        if rr.room_id is None:
            raise Conflict("ROOM_NOT_ASSIGNED")

    rooms = {
        r.id: r for r in await db.scalars(select(Room).where(Room.id.in_([rr.room_id for rr in targets])))
    }
    not_ready = []
    for rr in targets:
        room = rooms[rr.room_id]
        other = await _occupant(db, room.id, rr.id)
        if other is not None:
            raise Conflict("ROOM_STILL_OCCUPIED", params={"room": room.number, "reservation": other.code})
        if room.housekeeping_status in NOT_READY:
            not_ready.append(room)
    if not_ready and not ignore_room_status:
        raise Conflict(
            "ROOM_NOT_READY",
            params={"room": not_ready[0].number, "status": not_ready[0].housekeeping_status},
        )

    now = datetime.now(UTC)
    for rr in targets:
        rr.checked_in_at = now
    old_status = res.status
    res.status = "checked_in"
    _touch(res)
    await db.flush()
    numbers = sorted(rooms[rr.room_id].number for rr in targets)
    event(
        db,
        ctx,
        res,
        "checked_in",
        rooms=numbers,
        **{"from": old_status},
        room_not_ready=[r.number for r in not_ready],
    )
    await publish(
        db, ctx, res, "updated", {"status": [old_status, res.status], "checked_in": [None, numbers]}
    )
    await db.commit()
    return await load_reservation(db, ctx.hotel_id, res_id)


async def undo_check_in(
    db: AsyncSession, ctx: HotelContext, res_id: uuid.UUID, *, version: int, reservation_room_id: uuid.UUID
) -> Reservation:
    """Correct a check-in made by mistake (same hotel day only)."""
    res = await load_reservation(db, ctx.hotel_id, res_id, for_update=True)
    crud.check_version(res, version)
    rr = _select_stays(res, [reservation_room_id], [])[0]
    hotel = await _hotel(db, ctx.hotel_id)
    if rr.checked_in_at is None or rr.checked_out_at is not None:
        raise Conflict("NOT_IN_HOUSE")
    if rr.checked_in_at.astimezone(hotel.zone).date() != hotel_today(hotel):
        raise Conflict("UNDO_CHECK_IN_EXPIRED")
    rr.checked_in_at = None
    if not any(r.checked_in_at for r in res.rooms):
        res.status = "confirmed"
    _touch(res)
    await db.flush()
    room = await db.get(Room, rr.room_id) if rr.room_id else None
    event(db, ctx, res, "check_in_undone", room=room.number if room else None)
    await publish(db, ctx, res, "updated", {"status": ["checked_in", res.status]})
    await db.commit()
    return await load_reservation(db, ctx.hotel_id, res_id)


# --- check-out ----------------------------------------------------------------------


def _shorten(rr: ReservationRoom, new_departure: date) -> int:
    """Release the nights from `new_departure` on. Returns how many were removed."""
    kept = [n for n in rr.nights if n.night < new_departure]
    removed = len(rr.nights) - len(kept)
    rr.nights = kept
    rr.departure = new_departure
    rr.accommodation_total = sum((n.price for n in kept), ZERO)
    return removed


async def check_out(
    db: AsyncSession,
    ctx: HotelContext,
    res_id: uuid.UUID,
    *,
    version: int,
    reservation_room_ids: list[uuid.UUID] | None,
    shorten_stay: bool,
    allow_open_balance: bool,
) -> Reservation:
    res = await load_reservation(db, ctx.hotel_id, res_id, for_update=True)
    crud.check_version(res, version)
    if res.status != "checked_in":
        raise Conflict("INVALID_STATUS_TRANSITION", params={"from": res.status, "to": "checked_out"})
    hotel = await _hotel(db, ctx.hotel_id)
    today = hotel_today(hotel)
    in_house = [rr for rr in res.rooms if rr.checked_in_at and not rr.checked_out_at]
    targets = _select_stays(res, reservation_room_ids, in_house)
    if not targets:
        raise Conflict("NOTHING_TO_CHECK_OUT")
    for rr in targets:
        if rr not in in_house:
            raise Conflict("NOT_IN_HOUSE")

    # Early departure: nights from today on are given up (at least one night is kept).
    early = []
    for rr in targets:
        new_departure = max(today, rr.arrival + timedelta(days=1))
        if new_departure < rr.departure:
            early.append((rr, new_departure))
    if early and not shorten_stay:
        rr, new_departure = early[0]
        raise Conflict(
            "EARLY_DEPARTURE",
            params={"departure": rr.departure.isoformat(), "nights": (rr.departure - new_departure).days},
        )
    affected_types = {rr.room_type_id for rr, _ in early}
    if affected_types:
        await inventory.lock_room_types(db, ctx.hotel_id, affected_types)
    released = {}
    for rr, new_departure in early:
        released[str(rr.id)] = {
            "from": rr.departure,
            "to": new_departure,
            "nights": _shorten(rr, new_departure),
        }

    now = datetime.now(UTC)
    for rr in targets:
        rr.checked_out_at = now
    await db.flush()
    await folio.recompute(db, res)

    awaiting = [
        rr for rr in res.rooms if rr.occupies_inventory and rr.checked_in_at is None and rr.departure > today
    ]
    still_in = [rr for rr in res.rooms if rr.checked_in_at and not rr.checked_out_at]
    fully_out = not still_in and not awaiting
    balance = res.grand_total - res.paid_total
    if fully_out and balance != ZERO:
        if not allow_open_balance:
            code = "BALANCE_DUE" if balance > ZERO else "CREDIT_BALANCE"
            params = {"balance": str(abs(balance)), "currency": res.currency}
            if res.company_account_id and balance > ZERO:
                # Billed to a company: what can go to its account, what the guest owes.
                company = (await folio.statement(db, res, "company")).totals.balance
                params["company_balance"] = str(max(company, ZERO))
                params["guest_balance"] = str(max(balance - max(company, ZERO), ZERO))
            raise Conflict(code, params=params)
        if balance > ZERO and not ctx.has(P.FOLIO_ADJUST):
            raise Forbidden("PERMISSION_DENIED", params={"permission": P.FOLIO_ADJUST})
    if fully_out:
        res.status = "checked_out"
    _touch(res)
    await db.flush()

    rooms = {
        r.id: r for r in await db.scalars(select(Room).where(Room.id.in_([rr.room_id for rr in targets])))
    }
    for rr in targets:
        await after_departure(db, ctx, rooms[rr.room_id], today, "check_out", rr.id)
    numbers = sorted(rooms[rr.room_id].number for rr in targets)
    event(
        db,
        ctx,
        res,
        "checked_out",
        rooms=numbers,
        early_departure=released,
        open_balance=balance if fully_out and balance != ZERO else None,
    )
    await publish(
        db, ctx, res, "updated", {"checked_out": [None, numbers], "status": ["checked_in", res.status]}
    )
    await db.commit()
    return await load_reservation(db, ctx.hotel_id, res_id)


# --- in-house room move ---------------------------------------------------------------


async def move_in_house(
    db: AsyncSession,
    ctx: HotelContext,
    res_id: uuid.UUID,
    rr_id: uuid.UUID,
    *,
    version: int,
    room_id: uuid.UUID,
    ignore_room_status: bool,
    reason: str | None,
) -> Reservation:
    res = await load_reservation(db, ctx.hotel_id, res_id, for_update=True)
    crud.check_version(res, version)
    rr = _select_stays(res, [rr_id], [])[0]
    if rr.checked_in_at is None or rr.checked_out_at is not None:
        raise Conflict("NOT_IN_HOUSE")
    if room_id == rr.room_id:
        return res
    hotel = await _hotel(db, ctx.hotel_id)
    today = hotel_today(hotel)
    if today >= rr.departure:
        raise Conflict("STAY_ALREADY_ENDED", params={"departure": rr.departure.isoformat()})
    new_room = await crud.get_scoped(db, Room, ctx.hotel_id, room_id, code="ROOM_NOT_FOUND")
    if not new_room.is_active:
        raise ValidationFailed("ROOM_INACTIVE", params={"room": new_room.number})
    old_room = await db.get(Room, rr.room_id) if rr.room_id else None
    new_type = await db.get(RoomType, new_room.room_type_id)
    assert new_type is not None
    _check_occupancy(new_type, new_room, rr.adults, rr.children)
    other = await _occupant(db, new_room.id, rr.id)
    if other is not None:
        raise Conflict("ROOM_STILL_OCCUPIED", params={"room": new_room.number, "reservation": other.code})
    if new_room.housekeeping_status in NOT_READY and not ignore_room_status:
        raise Conflict(
            "ROOM_NOT_READY", params={"room": new_room.number, "status": new_room.housekeeping_status}
        )
    affected = {rr.room_type_id, new_room.room_type_id}
    await inventory.lock_room_types(db, ctx.hotel_id, affected)

    now = datetime.now(UTC)
    if today <= rr.arrival:
        # Nothing consumed yet: the whole stay changes room.
        rr.room_id = new_room.id
        rr.room_type_id = new_room.room_type_id
    else:
        moving = [n for n in rr.nights if n.night >= today]
        new_rr = ReservationRoom(
            id=uuid.uuid4(),
            hotel_id=ctx.hotel_id,
            room_type_id=new_room.room_type_id,
            room_id=new_room.id,
            rate_plan_id=rr.rate_plan_id,
            arrival=today,
            departure=rr.departure,
            adults=rr.adults,
            children=rr.children,
            occupies_inventory=True,
            accommodation_total=sum((n.price for n in moving), ZERO),
            checked_in_at=now,
        )
        new_rr.nights = [
            ReservationNight(
                night=n.night,
                hotel_id=ctx.hotel_id,
                price=n.price,
                price_source=n.price_source,
                rate_plan_id=n.rate_plan_id,
            )
            for n in moving
        ]
        _shorten(rr, today)
        rr.checked_out_at = now
        await db.flush()  # free the old room from today before allocating the new one
        res.rooms.append(new_rr)
    _touch(res)
    await db.flush()  # exclusion constraint: the new room must be free until departure
    short = await inventory.oversold_nights(
        db, ctx.hotel_id, affected, today, max(r.departure for r in res.rooms)
    )
    if short and not res.is_overbooked:
        raise Conflict(
            "NO_AVAILABILITY",
            params={"night": short[0].night.isoformat(), "room_type_id": str(short[0].room_type_id)},
        )
    await folio.recompute(db, res)
    await db.flush()
    if old_room:
        await after_departure(db, ctx, old_room, today, "room_move", rr.id)
    event(
        db,
        ctx,
        res,
        "room_moved",
        reservation_room_id=rr.id,
        old_room=old_room.number if old_room else None,
        new_room=new_room.number,
        effective=today,
        reason=reason,
    )
    await publish(db, ctx, res, "updated", {"room": [old_room.number if old_room else None, new_room.number]})
    await db.commit()
    return await load_reservation(db, ctx.hotel_id, res_id)


# --- daily views ------------------------------------------------------------------------


async def _stay_rows(db: AsyncSession, hotel_id: uuid.UUID, *conditions: Any) -> list[dict[str, Any]]:
    stmt = (
        select(ReservationRoom, Reservation, Guest, Room)
        .join(Reservation, Reservation.id == ReservationRoom.reservation_id)
        .join(Guest, Guest.id == Reservation.booker_guest_id)
        .outerjoin(Room, Room.id == ReservationRoom.room_id)
        .where(
            ReservationRoom.hotel_id == hotel_id, ReservationRoom.occupies_inventory.is_(True), *conditions
        )
        .order_by(Room.number.nulls_last(), Reservation.code)
    )
    rows = []
    for rr, res, guest, room in (await db.execute(stmt)).all():
        rows.append(
            {
                "reservation_id": res.id,
                "code": res.code,
                "status": res.status,
                "version": res.version,
                "reservation_room_id": rr.id,
                "guest_id": guest.id,
                "guest_name": f"{guest.first_name} {guest.last_name}".strip(),
                "vip_level": guest.vip_level,
                "room_id": rr.room_id,
                "room_number": room.number if room else None,
                "room_type_id": rr.room_type_id,
                "housekeeping_status": room.housekeeping_status if room else None,
                "arrival": rr.arrival,
                "departure": rr.departure,
                "adults": rr.adults,
                "children": rr.children,
                "checked_in_at": rr.checked_in_at,
                "checked_out_at": rr.checked_out_at,
                "balance": res.grand_total - res.paid_total,
                "currency": res.currency,
                "special_requests": res.special_requests,
                "flags": [],
            }
        )
    return rows


async def front_desk(db: AsyncSession, ctx: HotelContext, day: date | None) -> dict[str, Any]:
    hotel = await _hotel(db, ctx.hotel_id)
    today = hotel_today(hotel)
    day = day or today
    open_statuses = ("pending", "confirmed", "checked_in")
    # Expected today, plus late arrivals still expected (arrival passed, not arrived).
    arrivals = await _stay_rows(
        db,
        ctx.hotel_id,
        Reservation.status.in_(open_statuses),
        or_(
            ReservationRoom.arrival == day,
            and_(
                ReservationRoom.arrival < day,
                ReservationRoom.departure > day,
                ReservationRoom.checked_in_at.is_(None),
            ),
        ),
    )
    for r in arrivals:
        if r["arrival"] < day:
            r["flags"].append("late_arrival")
    # Due out today: in house, or already checked out today.
    departures = await _stay_rows(
        db,
        ctx.hotel_id,
        Reservation.status.in_(("checked_in", "checked_out")),
        ReservationRoom.checked_in_at.is_not(None),
        or_(
            and_(ReservationRoom.departure <= day, ReservationRoom.checked_out_at.is_(None)),
            and_(ReservationRoom.departure == day, ReservationRoom.checked_out_at.is_not(None)),
        ),
    )
    in_house = await _stay_rows(
        db,
        ctx.hotel_id,
        ReservationRoom.checked_in_at.is_not(None),
        ReservationRoom.checked_out_at.is_(None),
    )
    for group in (departures, in_house):
        for r in group:
            if r["departure"] < day and r["checked_out_at"] is None:
                r["flags"].append("overdue")
    return {
        "date": day,
        "is_today": day == today,
        "arrivals": arrivals,
        "departures": departures,
        "in_house": in_house,
    }


async def room_board(db: AsyncSession, ctx: HotelContext) -> list[dict[str, Any]]:
    hotel = await _hotel(db, ctx.hotel_id)
    today = hotel_today(hotel)
    rooms = list(
        await db.scalars(
            select(Room)
            .where(Room.hotel_id == ctx.hotel_id, Room.is_active.is_(True))
            .order_by(Room.sort_order, Room.number)
        )
    )
    blocks = {
        b.room_id: b
        for b in await db.scalars(
            select(RoomBlock).where(
                RoomBlock.hotel_id == ctx.hotel_id, RoomBlock.start_date <= today, RoomBlock.end_date > today
            )
        )
    }
    occupants = {
        r["room_id"]: r
        for r in await _stay_rows(
            db,
            ctx.hotel_id,
            ReservationRoom.room_id.is_not(None),
            ReservationRoom.checked_in_at.is_not(None),
            ReservationRoom.checked_out_at.is_(None),
        )
    }
    arriving = {
        r["room_id"]: r
        for r in await _stay_rows(
            db,
            ctx.hotel_id,
            ReservationRoom.room_id.is_not(None),
            ReservationRoom.checked_in_at.is_(None),
            ReservationRoom.arrival <= today,
            ReservationRoom.departure > today,
            Reservation.status.in_(tuple(s for s in OCCUPYING_STATUSES if s != "checked_out")),
        )
    }
    tasks: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for t in await housekeeping.list_tasks(db, ctx, day=today):
        tasks.setdefault(t["room_id"], []).append(
            {
                k: t[k]
                for k in (
                    "id",
                    "task_type",
                    "status",
                    "priority",
                    "assigned_to",
                    "assigned_to_name",
                    "version",
                )
            }
        )
    maintenance = await maintenance_service.open_by_room(db, ctx.hotel_id)
    out = []
    for room in rooms:
        occ = occupants.get(room.id)
        block = blocks.get(room.id)
        out.append(
            {
                "room_id": room.id,
                "number": room.number,
                "room_type_id": room.room_type_id,
                "floor_id": room.floor_id,
                "housekeeping_status": room.housekeeping_status,
                "version": room.version,
                "block": {
                    "id": block.id,
                    "reason": block.reason,
                    "start_date": block.start_date,
                    "end_date": block.end_date,
                }
                if block
                else None,
                "occupant": occ,
                "arriving": arriving.get(room.id),
                "departing": bool(occ and occ["departure"] <= today),
                "tasks": tasks.get(room.id, []),
                "maintenance": maintenance.get(room.id),
            }
        )
    return out
