"""Shared settlement rules for sales outside the room folio (restaurant & bar
checks, vehicle rentals): tendering money in any accepted currency, cash
change, and charging a guest's room.

Rules:
* The amount is converted at the configured rate; a stale rate shown to the
  user is refused (EXCHANGE_RATE_CHANGED).
* Cash may exceed the balance: the balance is kept and the rest is change.
  Other methods cannot exceed the balance.
* A room charge posts the sale to the in-house guest's folio as an "outlet"
  charge carrying the sale's own tax lines (no second taxation).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import HotelContext
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed, field_error
from app.core.money import ZERO, round_money
from app.core.permissions import P
from app.modules.billing import service as billing
from app.modules.billing.models import FolioCharge
from app.modules.guests.models import Guest
from app.modules.hotels.models import Hotel
from app.modules.reservations.models import Reservation, ReservationRoom
from app.modules.rooms.models import Room


@dataclass
class Tender:
    method: str
    amount: Decimal  # kept, in `currency`
    currency: str
    exchange_rate: Decimal
    amount_base: Decimal
    tendered: Decimal | None  # cash handed over when it exceeded the balance
    change: Decimal | None


async def tender(db: AsyncSession, hotel: Hotel, balance: Decimal, data: Any) -> Tender:
    """Validate and convert a non-room-charge payment against a balance."""
    base_cur = hotel.currency_code
    currency = data.currency or base_cur
    rate = await billing.current_rate(db, hotel, currency)
    if data.exchange_rate is not None and data.exchange_rate != rate:
        raise Conflict("EXCHANGE_RATE_CHANGED", params={"currency": currency, "rate": str(rate)})
    amount = data.amount
    amount_base = round_money(amount / rate, base_cur)
    if amount_base <= ZERO:
        raise ValidationFailed("AMOUNT_TOO_SMALL", fields=[field_error("amount", "AMOUNT_TOO_SMALL")])
    tendered = change = None
    if amount_base > balance:
        if data.method != "cash":
            raise Conflict("PAYMENT_EXCEEDS_BALANCE", params={"balance": str(balance)})
        tendered = amount
        amount = round_money(balance * rate, currency)
        amount_base = balance
        change = tendered - amount
    return Tender(data.method, amount, currency, rate, amount_base, tendered, change)


async def in_house_stay(db: AsyncSession, hotel_id: uuid.UUID, rr_id: uuid.UUID) -> ReservationRoom:
    rr = (
        await db.scalars(
            select(ReservationRoom).where(ReservationRoom.id == rr_id, ReservationRoom.hotel_id == hotel_id)
        )
    ).one_or_none()
    if rr is None:
        raise NotFound("RESERVATION_ROOM_NOT_FOUND")
    if rr.checked_in_at is None or rr.checked_out_at is not None:
        raise Conflict("GUEST_NOT_IN_HOUSE")
    return rr


async def charge_to_room(
    db: AsyncSession,
    ctx: HotelContext,
    rr: ReservationRoom,
    *,
    name: dict[str, str],
    reference: str,
    total: Decimal,
    tax_total: Decimal,
    tax_lines: list[dict[str, Any]],
    service_date: date,
) -> FolioCharge:
    """Post a whole sale (total incl. exclusive taxes) to the guest's folio."""
    res = await billing.load_reservation(db, ctx.hotel_id, rr.reservation_id, for_update=True)
    return await billing.post_outlet_charge(
        db,
        ctx,
        res,
        reservation_room_id=rr.id,
        name=name,
        description=reference,
        net_amount=total - tax_total,
        tax_lines=tax_lines,
        service_date=service_date,
    )


async def void_room_charge(
    db: AsyncSession, ctx: HotelContext, folio_charge_id: uuid.UUID, reason: str
) -> None:
    charge = await db.get(FolioCharge, folio_charge_id)
    assert charge is not None
    res = await billing.load_reservation(db, ctx.hotel_id, charge.reservation_id, for_update=True)
    await billing.void_charge_tx(db, ctx, res, charge, reason)


SETTLE_PERMISSIONS = (P.RESTAURANT_SETTLE, P.VEHICLES_RENT, P.PAYMENTS_RECORD)


async def in_house_guests(db: AsyncSession, ctx: HotelContext, q: str | None) -> list[dict[str, Any]]:
    """Guests staying right now (to charge a sale to their room)."""
    if not any(ctx.has(p) for p in SETTLE_PERMISSIONS):
        raise Forbidden("PERMISSION_DENIED", params={"permission": P.RESTAURANT_SETTLE})
    stmt = (
        select(ReservationRoom, Reservation, Guest, Room)
        .join(Reservation, Reservation.id == ReservationRoom.reservation_id)
        .join(Guest, Guest.id == Reservation.booker_guest_id)
        .outerjoin(Room, Room.id == ReservationRoom.room_id)
        .where(
            ReservationRoom.hotel_id == ctx.hotel_id,
            ReservationRoom.checked_in_at.is_not(None),
            ReservationRoom.checked_out_at.is_(None),
        )
    )
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            Room.number.ilike(like)
            | func.concat(Guest.first_name, " ", Guest.last_name).ilike(like)
            | Reservation.code.ilike(like)
        )
    rows = (await db.execute(stmt.order_by(Room.number).limit(50))).all()
    return [
        {
            "reservation_room_id": rr.id,
            "reservation_id": res.id,
            "reservation_code": res.code,
            "room_number": room.number if room else None,
            "guest_name": f"{g.first_name} {g.last_name}".strip(),
            "in_house": True,
        }
        for rr, res, g, room in rows
    ]
