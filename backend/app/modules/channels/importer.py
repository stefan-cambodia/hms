"""Bookings received from a channel → reservations.

Rules (channel manager design §3.2):

* Idempotent: one row per (connection, provider reservation id, revision id);
  a revision received again is not imported again, only re-acknowledged.
* Out of order: a revision older than one already applied is ignored; a
  modification received before the booking creates it; a booking received
  after its cancellation is ignored.
* Never refused for availability: channel bookings may overbook, which is
  flagged on the reservation and announced to connected users.
* Same rules as manual bookings otherwise: the reservations engine creates,
  modifies and cancels them (allocation ledger, folio, history, audit).
* Prices are the channel's (what the guest agreed to pay), converted to the
  hotel's price convention (taxes) and currency.
* Card data never reaches this module (see adapters/base.py).
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.context import Actor, HotelContext
from app.core.errors import AppError
from app.core.money import ZERO, round_money
from app.core.permissions import ALL_PERMISSIONS
from app.core.schemas import mask_card_numbers
from app.modules.billing import service as billing
from app.modules.channels.adapters.base import InboundBooking, InboundStay
from app.modules.channels.adapters.siteminder import CHANNEL_SOURCES
from app.modules.channels.models import ChannelBooking, ChannelConnection, ChannelRateMap, ChannelRoomMap
from app.modules.guests.schemas import GuestIn
from app.modules.hotels.models import Hotel
from app.modules.pricing import service as pricing
from app.modules.reservations import service as reservations
from app.modules.reservations.models import Reservation
from app.modules.reservations.schemas import ReservationIn, StayIn
from app.modules.rooms.models import RoomType


class ImportFailed(Exception):
    """A permanent problem with this booking (reported to the provider)."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail[:500]


def system_context(conn: ChannelConnection, organization_id: uuid.UUID | None) -> HotelContext:
    return HotelContext(
        actor=Actor.system(organization_id, source="channel"),
        hotel_id=conn.hotel_id,
        permissions=frozenset(ALL_PERMISSIONS),
    )


def _jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {k: _jsonable(v) for k, v in dataclasses.asdict(value).items()}
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


async def store(db: AsyncSession, conn: ChannelConnection, booking: InboundBooking) -> ChannelBooking:
    """Record the revision (once) and return its row."""
    stmt = (
        insert(ChannelBooking)
        .values(
            id=uuid.uuid4(),
            connection_id=conn.id,
            hotel_id=conn.hotel_id,
            external_id=booking.external_id[:100],
            revision=booking.message_id[:100],
            action=booking.action,
            channel_name=(booking.channel_name or booking.channel_code or None),
            message_at=booking.message_at,
            data=_jsonable(dataclasses.replace(booking, card_brand=None, card_last4=None)),
            card_brand=(booking.card_brand or None) and booking.card_brand[:20],
            card_last4=booking.card_last4,
        )
        .on_conflict_do_nothing(index_elements=["connection_id", "external_id", "revision"])
    )
    await db.execute(stmt)
    row = (
        await db.scalars(
            select(ChannelBooking).where(
                ChannelBooking.connection_id == conn.id,
                ChannelBooking.external_id == booking.external_id[:100],
                ChannelBooking.revision == booking.message_id[:100],
            )
        )
    ).one()
    return row


async def _existing_reservation(db: AsyncSession, row: ChannelBooking) -> Reservation | None:
    res_id = await db.scalar(
        select(ChannelBooking.reservation_id)
        .where(
            ChannelBooking.connection_id == row.connection_id,
            ChannelBooking.external_id == row.external_id,
            ChannelBooking.reservation_id.is_not(None),
        )
        .order_by(ChannelBooking.received_at.desc())
        .limit(1)
    )
    if res_id is None:
        return None
    return await reservations.get_reservation(db, row.hotel_id, res_id)


async def _newer_applied(db: AsyncSession, row: ChannelBooking) -> ChannelBooking | None:
    """A revision of the same booking, already processed, with a later timestamp."""
    if row.message_at is None:
        return None
    return (
        await db.scalars(
            select(ChannelBooking)
            .where(
                ChannelBooking.connection_id == row.connection_id,
                ChannelBooking.external_id == row.external_id,
                ChannelBooking.id != row.id,
                ChannelBooking.import_status.in_(("imported", "ignored")),
                ChannelBooking.message_at > row.message_at,
            )
            .limit(1)
        )
    ).one_or_none()


async def process(db: AsyncSession, conn: ChannelConnection, booking: InboundBooking) -> ChannelBooking:
    """Store and import one revision. Commits. Unexpected errors propagate
    (the revision stays pending and is retried at the next pull)."""
    row = await store(db, conn, booking)
    if row.import_status in ("imported", "ignored", "failed"):
        await db.commit()
        return row
    row.attempts += 1
    hotel = await db.get(Hotel, conn.hotel_id)
    assert hotel is not None
    ctx = system_context(conn, hotel.organization_id)
    try:
        async with db.begin_nested():
            await _apply(db, ctx, hotel, conn, booking, row)
    except ImportFailed as exc:
        row.import_status, row.error_code, row.error_detail = "failed", exc.code, exc.detail
    except AppError as exc:
        row.import_status, row.error_code = "failed", exc.code
        row.error_detail = str(exc.params or exc.message)[:500]
    row.processed_at = datetime.now(UTC)
    if row.import_status == "failed" or row.overbooked:
        await events.emit(
            db,
            hotel_id=conn.hotel_id,
            entity="channel_booking",
            action="attention",
            entity_id=row.id,
            actor=ctx.actor,
            extra={"status": row.import_status, "overbooked": row.overbooked, "code": row.error_code},
        )
    await db.commit()
    return row


async def _apply(
    db: AsyncSession,
    ctx: HotelContext,
    hotel: Hotel,
    conn: ChannelConnection,
    booking: InboundBooking,
    row: ChannelBooking,
) -> None:
    if booking.hotel_code and booking.hotel_code != conn.hotel_code:
        raise ImportFailed("WRONG_HOTEL", f"Booking for hotel code {booking.hotel_code}")
    newer = await _newer_applied(db, row)
    existing = await _existing_reservation(db, row)
    if newer is not None:
        _ignore(row, existing, "OLDER_REVISION", "A more recent revision was already applied")
        return
    if booking.action == "cancel":
        if existing is None:
            _ignore(row, None, "UNKNOWN_BOOKING", "Cancellation of a booking that was never received")
            return
        if existing.status == "cancelled":
            _ignore(row, existing, "ALREADY_CANCELLED", "Already cancelled")
            return
        if existing.status not in ("pending", "confirmed"):
            raise ImportFailed(
                "CANCEL_NOT_POSSIBLE", f"Reservation {existing.code} is {existing.status}: cancel it manually"
            )
        await reservations.cancel(
            db,
            ctx,
            existing.id,
            existing.version,
            f"Cancelled by {booking.channel_name or conn.name} ({booking.external_id})"[:500],
            waive_fee=True,  # the channel applies its own cancellation terms
            commit=False,
        )
        row.import_status, row.reservation_id = "imported", existing.id
        return

    stays, night_prices = await _stays(db, hotel, conn, booking)
    if existing is not None:
        await reservations.apply_channel_modification(
            db,
            ctx,
            existing,
            [
                reservations.ChannelStay(
                    room_type_id=s.room_type_id,
                    rate_plan_id=s.rate_plan_id,
                    arrival=s.arrival or booking.stays[0].arrival,
                    departure=s.departure or booking.stays[0].departure,
                    adults=s.adults,
                    children=s.children,
                    prices=prices,
                )
                for s, prices in zip(stays, night_prices, strict=True)
            ],
            reference=booking.external_id,
        )
        existing.external_ref = (booking.channel_reference or booking.external_id)[:100]
        row.import_status, row.reservation_id, row.overbooked = (
            "imported",
            existing.id,
            existing.is_overbooked,
        )
        return

    data = ReservationIn(
        arrival=min(s.arrival for s in booking.stays),
        departure=max(s.departure for s in booking.stays),
        rooms=stays,
        guest=_guest(booking),
        status="confirmed",
        source=CHANNEL_SOURCES.get(booking.channel_code or "", "other"),  # type: ignore[arg-type]
        external_ref=(booking.channel_reference or booking.external_id)[:100],
        special_requests=_notes(booking.comments),
        internal_notes=_internal_notes(conn, booking),
        allow_overbooking=True,
        override_restrictions=True,
    )
    res, _ = await reservations.create_reservation(db, ctx, data, night_prices=night_prices, commit=False)
    row.import_status, row.reservation_id, row.overbooked = "imported", res.id, res.is_overbooked


def _ignore(row: ChannelBooking, res: Reservation | None, code: str, detail: str) -> None:
    row.import_status, row.error_code, row.error_detail = "ignored", code, detail
    row.reservation_id = res.id if res else None


async def _stays(
    db: AsyncSession, hotel: Hotel, conn: ChannelConnection, booking: InboundBooking
) -> tuple[list[StayIn], list[reservations.ChannelNights]]:
    if not booking.stays:
        raise ImportFailed("NO_ROOM_STAY", "The message contains no room stay")
    rooms = {
        m.external_code: m.room_type_id
        for m in await db.scalars(select(ChannelRoomMap).where(ChannelRoomMap.connection_id == conn.id))
    }
    rates = list(await db.scalars(select(ChannelRateMap).where(ChannelRateMap.connection_id == conn.id)))
    rate_by_code = {(m.room_type_id, m.external_code): m.rate_plan_id for m in rates}
    rate_any = {m.external_code: m.rate_plan_id for m in rates}
    rate = Decimal(1)
    if booking.currency and booking.currency != hotel.currency_code:
        try:
            rate = await billing.current_rate(db, hotel, booking.currency)
        except AppError as exc:
            raise ImportFailed(
                "CURRENCY_NOT_CONFIGURED",
                f"Amounts are in {booking.currency}, which has no exchange rate in the PMS",
            ) from exc
    taxes = await pricing.active_taxes(db, hotel.id, "accommodation")
    out: list[StayIn] = []
    prices: list[reservations.ChannelNights] = []
    for s in booking.stays:
        rt_id = rooms.get(s.room_code or "")
        if rt_id is None:
            raise ImportFailed("UNMAPPED_ROOM", f"Room type code {s.room_code!r} is not mapped in the PMS")
        rt = await db.get(RoomType, rt_id)
        assert rt is not None
        plan_id = rate_by_code.get((rt_id, s.rate_code or "")) or rate_any.get(s.rate_code or "")
        if s.departure <= s.arrival:
            raise ImportFailed("INVALID_DATES", f"{s.arrival} to {s.departure}")
        # A channel booking is never refused for occupancy: guest counts above
        # the category's capacity are capped, and the booked numbers kept in the notes.
        adults = min(max(1, s.adults), rt.max_adults)
        children = min(s.children, rt.max_children, rt.max_occupancy - adults)
        if (adults, children) != (s.adults, s.children):
            booking.extra[f"guests booked ({s.room_code})"] = f"{s.adults} adults, {s.children} children"
        out.append(
            StayIn(
                room_type_id=rt_id,
                arrival=s.arrival,
                departure=s.departure,
                adults=adults,
                children=max(0, children),
                rate_plan_id=plan_id,
            )
        )
        prices.append(_night_prices(hotel, taxes, rt, s, booking, rate, rate_by_code, rate_any, rt_id))
    return out, prices


def _night_prices(
    hotel: Hotel,
    taxes: list[Any],
    rt: RoomType,
    stay: InboundStay,
    booking: InboundBooking,
    units_per_base: Decimal,
    rate_by_code: dict[tuple[uuid.UUID, str], uuid.UUID],
    rate_any: dict[str, uuid.UUID],
    rt_id: uuid.UUID,
) -> reservations.ChannelNights:
    """The channel's nightly amounts as PMS prices (hotel currency, the
    hotel's tax convention: inclusive taxes included, exclusive ones added
    by the folio)."""
    nights = {(stay.arrival + timedelta(days=i)) for i in range((stay.departure - stay.arrival).days)}
    amounts: dict[date, tuple[Decimal, str | None]] = {
        n.night: (n.amount, n.rate_code) for n in stay.nights if n.night in nights
    }
    if not amounts and stay.total is not None and nights:
        # Only a stay total: spread it evenly (the channel did the same).
        each = stay.total / len(nights)
        amounts = {n: (each, stay.rate_code) for n in nights}
    incl_pct = sum((t.rate for t in taxes if t.kind == "percent" and t.is_inclusive), ZERO)
    excl_pct = sum((t.rate for t in taxes if t.kind == "percent" and not t.is_inclusive), ZERO)
    fixed = sum((t.rate for t in taxes if t.kind == "fixed_per_night" and not t.is_inclusive), ZERO)
    fixed += sum(
        (
            t.rate * (stay.adults + stay.children)
            for t in taxes
            if t.kind == "fixed_per_person_night" and not t.is_inclusive
        ),
        ZERO,
    )
    # price p → amount after tax: p + p·excl/(100 + incl) + fixed  (see compute_taxes)
    factor = 1 + excl_pct / (100 + incl_pct)
    out: reservations.ChannelNights = {}
    for night, (amount, rate_code) in amounts.items():
        base = amount / units_per_base
        if booking.amounts_after_tax:
            price = (base - fixed) / factor
        else:
            price = base * (1 + incl_pct / 100)
        plan_id = rate_by_code.get((rt_id, rate_code or "")) or rate_any.get(rate_code or "")
        out[night] = (round_money(max(price, ZERO), hotel.currency_code), plan_id)
    return out


def _guest(booking: InboundBooking) -> GuestIn:
    g = booking.booker
    first = (g.first_name if g else "") or "-"
    last = (g.last_name if g else "") or (booking.channel_name or "Channel booking")
    base = {"first_name": first[:100], "last_name": last[:100]}
    extra: dict[str, Any] = {}
    if g:
        if g.email:
            extra["email"] = g.email
        if g.phone:
            extra["phone"] = "".join(ch for ch in g.phone if ch.isdigit() or ch in "+()-. ")[:40] or None
        if g.country:
            extra["nationality"] = g.country
    try:
        return GuestIn(**base, **extra)
    except ValidationError:
        # Keep the booking even when the channel sends a malformed email or phone.
        return GuestIn(**base)


def _notes(comments: list[str]) -> str | None:
    text = "\n".join(c for c in comments if c).strip()
    return mask_card_numbers(text)[:2000] or None if text else None


def _internal_notes(conn: ChannelConnection, booking: InboundBooking) -> str:
    parts = [f"{conn.name}: {booking.external_id}"]
    if booking.channel_name or booking.channel_code:
        parts.append(f"{booking.channel_name or ''} ({booking.channel_code or '?'})".strip())
    if booking.total is not None:
        parts.append(f"channel total {booking.total} {booking.currency or ''}".strip())
    if booking.card_brand or booking.card_last4:
        parts.append(f"card guarantee {booking.card_brand or ''} ••••{booking.card_last4 or '????'}".strip())
    for key, value in booking.extra.items():
        parts.append(f"{key}: {value if not isinstance(value, list) else '; '.join(value)}")
    return mask_card_numbers(" · ".join(parts))[:2000]
