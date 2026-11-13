"""End-of-day closure (night audit).

Run after midnight for the day that ended: the screen lists what is still
open for that day (guests expected who did not arrive, guests due out still
in house, open restaurant checks, vehicles not returned, tomorrow's arrivals
without a room, balances due), shows the day's figures, and closes the day.

Closing records the day's report as it stands (`DayClosure`, append-only) and
freezes the day (`lock.py`). Days are closed in order, and only once they are
over. Figures come from the same engines as the rest of the system: the KPI
engine for rooms and revenue, the payment tables for the cash-up.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit, events
from app.core.context import HotelContext
from app.core.errors import Conflict, NotFound, ValidationFailed, field_error
from app.core.money import ZERO
from app.core.permissions import P
from app.modules.auth.models import User
from app.modules.billing.models import Invoice, Payment
from app.modules.guests.models import Guest
from app.modules.hotels.models import Hotel
from app.modules.nightaudit.lock import last_closed
from app.modules.nightaudit.models import DayClosure
from app.modules.reports import service as reports
from app.modules.reservations.models import Reservation, ReservationRoom
from app.modules.restaurant.models import DiningTable, Order, Outlet
from app.modules.rooms.models import Room
from app.modules.vehicles.models import Rental, Vehicle


async def _hotel(db: AsyncSession, hotel_id: uuid.UUID) -> Hotel:
    hotel = await db.get(Hotel, hotel_id)
    if hotel is None:
        raise NotFound("HOTEL_NOT_FOUND")
    return hotel


def _bounds(hotel: Hotel, day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, hotel.zone)
    return start, start + timedelta(days=1)


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


# --- what is still open for a day ------------------------------------------------


async def _stays(db: AsyncSession, hotel_id: uuid.UUID, *conditions: Any) -> list[dict[str, Any]]:
    rows = await db.execute(
        select(ReservationRoom, Reservation, Guest, Room.number)
        .join(Reservation, Reservation.id == ReservationRoom.reservation_id)
        .join(Guest, Guest.id == Reservation.booker_guest_id)
        .outerjoin(Room, Room.id == ReservationRoom.room_id)
        .where(
            ReservationRoom.hotel_id == hotel_id, ReservationRoom.occupies_inventory.is_(True), *conditions
        )
        .order_by(ReservationRoom.arrival, Reservation.code)
    )
    return [
        {
            "reservation_id": res.id,
            "code": res.code,
            "version": res.version,
            "status": res.status,
            "source": res.source,
            "guest_name": f"{guest.first_name} {guest.last_name}".strip(),
            "room_number": number,
            "arrival": rr.arrival,
            "departure": rr.departure,
            "balance": res.grand_total - res.paid_total,
            "currency": res.currency,
        }
        for rr, res, guest, number in rows.all()
    ]


async def open_items(db: AsyncSession, hotel: Hotel, day: date) -> dict[str, Any]:
    _, end = _bounds(hotel, day)
    not_arrived = await _stays(
        db,
        hotel.id,
        Reservation.status.in_(("pending", "confirmed")),
        ReservationRoom.checked_in_at.is_(None),
        ReservationRoom.arrival <= day,
        ReservationRoom.departure > day,
    )
    not_departed = await _stays(
        db,
        hotel.id,
        ReservationRoom.checked_in_at.is_not(None),
        ReservationRoom.checked_out_at.is_(None),
        ReservationRoom.departure <= day,
    )
    unassigned = await _stays(
        db,
        hotel.id,
        Reservation.status.in_(("pending", "confirmed")),
        ReservationRoom.room_id.is_(None),
        ReservationRoom.arrival == day + timedelta(days=1),
    )
    in_house = await _stays(
        db,
        hotel.id,
        ReservationRoom.checked_in_at.is_not(None),
        ReservationRoom.checked_out_at.is_(None),
    )
    seen: set[uuid.UUID] = set()
    balances = []
    for s in in_house:
        if s["balance"] > 0 and s["reservation_id"] not in seen:
            seen.add(s["reservation_id"])
            balances.append(s)
    checks = (
        await db.execute(
            select(Order, Outlet.name, DiningTable.label)
            .join(Outlet, Outlet.id == Order.outlet_id)
            .outerjoin(DiningTable, DiningTable.id == Order.table_id)
            .where(Order.hotel_id == hotel.id, Order.status == "open", Order.business_date <= day)
            .order_by(Order.business_date, Order.number)
        )
    ).all()
    rentals = (
        await db.execute(
            select(Rental, Vehicle.code)
            .join(Vehicle, Vehicle.id == Rental.vehicle_id)
            .where(Rental.hotel_id == hotel.id, Rental.status == "out", Rental.end_at < end)
            .order_by(Rental.end_at)
        )
    ).all()
    return {
        "not_arrived": not_arrived,
        "not_departed": not_departed,
        "open_checks": [
            {
                "order_id": o.id,
                "number": o.number,
                "outlet": outlet,
                "table": table,
                "order_type": o.order_type,
                "business_date": o.business_date,
                "total": o.total - o.paid_total,
            }
            for o, outlet, table in checks
        ],
        "overdue_rentals": [
            {"rental_id": r.id, "number": r.number, "vehicle": code, "end_at": r.end_at}
            for r, code in rentals
        ],
        "unassigned_tomorrow": unassigned,
        "balances_due": {
            "count": len(balances),
            "total": sum((b["balance"] for b in balances), ZERO),
            "stays": balances,
        },
    }


def _open_count(items: dict[str, Any]) -> int:
    """Items that call for a decision (balances due are information)."""
    keys = ("not_arrived", "not_departed", "open_checks", "overdue_rentals", "unassigned_tomorrow")
    return sum(len(items[k]) for k in keys)


# --- the day's figures -------------------------------------------------------------

_PAYMENTS = text(
    """
    SELECT 'folio' AS source, kind, method, currency, count(*), sum(amount), sum(amount_base)
    FROM payments WHERE hotel_id = :hotel AND NOT is_void AND method <> 'city_ledger'
      AND received_at >= :start AND received_at < :end
    GROUP BY kind, method, currency
    UNION ALL
    SELECT 'restaurant', 'payment', method, currency, count(*), sum(amount), sum(amount_base)
    FROM restaurant_payments
    WHERE hotel_id = :hotel AND NOT is_void AND method <> 'room_charge'
      AND received_at >= :start AND received_at < :end
    GROUP BY method, currency
    UNION ALL
    SELECT 'vehicles', 'payment', method, currency, count(*), sum(amount), sum(amount_base)
    FROM vehicle_rental_payments
    WHERE hotel_id = :hotel AND NOT is_void AND method <> 'room_charge'
      AND received_at >= :start AND received_at < :end
    GROUP BY method, currency
    UNION ALL
    SELECT 'accounts', 'payment', method, currency, count(*), sum(amount), sum(amount_base)
    FROM account_payments
    WHERE hotel_id = :hotel AND NOT is_void AND received_at >= :start AND received_at < :end
    GROUP BY method, currency
    ORDER BY 3, 4, 1, 2
    """
)


async def build_report(db: AsyncSession, hotel: Hotel, day: date) -> dict[str, Any]:
    start, end = _bounds(hotel, day)
    nxt = day + timedelta(days=1)
    rooms = await reports._totals(db, hotel, day, nxt, financial=True)
    bookings = await reports._bookings(db, hotel, day, nxt)
    revenue = await reports._other_revenue(db, hotel, day, nxt)
    tomorrow = await reports._totals(db, hotel, nxt, nxt + timedelta(days=1), financial=False)

    def count(*conditions: Any) -> Any:
        return (
            select(func.count())
            .select_from(ReservationRoom)
            .join(Reservation, Reservation.id == ReservationRoom.reservation_id)
            .where(ReservationRoom.hotel_id == hotel.id, *conditions)
        )

    movements = {
        "arrivals": await db.scalar(
            count(ReservationRoom.checked_in_at >= start, ReservationRoom.checked_in_at < end)
        ),
        "departures": await db.scalar(
            count(ReservationRoom.checked_out_at >= start, ReservationRoom.checked_out_at < end)
        ),
        "walk_ins": await db.scalar(
            count(
                Reservation.source == "walk_in",
                ReservationRoom.checked_in_at >= start,
                ReservationRoom.checked_in_at < end,
            )
        ),
        "no_shows": await db.scalar(count(Reservation.status == "no_show", ReservationRoom.arrival == day)),
        "bookings_made": bookings["created"],
        "cancellations": await db.scalar(
            select(func.count()).where(
                Reservation.hotel_id == hotel.id,
                Reservation.cancelled_at >= start,
                Reservation.cancelled_at < end,
            )
        ),
        "arrivals_tomorrow": await db.scalar(
            count(
                Reservation.status.in_(("pending", "confirmed")),
                ReservationRoom.occupies_inventory.is_(True),
                ReservationRoom.arrival == nxt,
            )
        ),
        "occupancy_tomorrow": tomorrow["occupancy"],
    }

    rows = (await db.execute(_PAYMENTS, {"hotel": hotel.id, "start": start, "end": end})).all()
    payments = [
        {
            "source": source,
            "kind": kind,
            "method": method,
            "currency": currency,
            "count": int(n),
            "amount": amount,
            "amount_base": base,
        }
        for source, kind, method, currency, n, amount, base in rows
    ]
    by_method: dict[str, Decimal] = {}
    for p in payments:
        signed = -p["amount_base"] if p["kind"] == "refund" else p["amount_base"]
        by_method[p["method"]] = by_method.get(p["method"], ZERO) + signed
    issued = (
        await db.execute(
            select(func.count(), func.coalesce(func.sum(Invoice.total), 0)).where(
                Invoice.hotel_id == hotel.id, Invoice.issue_date == day, Invoice.status != "void"
            )
        )
    ).one()
    voided = await db.scalar(
        select(func.count()).where(
            Invoice.hotel_id == hotel.id, Invoice.voided_at >= start, Invoice.voided_at < end
        )
    )
    # Balances transferred to company accounts: settled, but not money received.
    transfers = (
        await db.execute(
            select(func.count(), func.coalesce(func.sum(Payment.amount_base), 0)).where(
                Payment.hotel_id == hotel.id,
                Payment.method == "city_ledger",
                Payment.is_void.is_(False),
                Payment.received_at >= start,
                Payment.received_at < end,
            )
        )
    ).one()
    return {
        "date": day,
        "currency": hotel.currency_code,
        "rooms": rooms,
        "movements": movements,
        "revenue": {"rooms": rooms["revenue"], **revenue, "total": rooms["revenue"] + revenue["total"]},
        "payments": payments,
        "payments_by_method": [{"method": m, "amount_base": a} for m, a in sorted(by_method.items())],
        "payments_net": sum(by_method.values(), ZERO),
        "invoices": {"issued": int(issued[0]), "total": issued[1], "voided": int(voided or 0)},
        "transfers": {"count": int(transfers[0]), "total": transfers[1]},
    }


def _hide_money(report: dict[str, Any], ctx: HotelContext) -> dict[str, Any]:
    """Revenue for financial reports, cash-up for payment viewers (as elsewhere)."""
    out = dict(report)
    if not ctx.has(P.REPORTS_FINANCIAL):
        out["rooms"] = {**report["rooms"], "revenue": None, "adr": None, "revpar": None}
        out["revenue"] = None
    if not ctx.has(P.PAYMENTS_VIEW):
        out["payments"], out["payments_by_method"], out["payments_net"] = [], [], None
        out["invoices"] = None
        out["transfers"] = None
    return out


# --- overview, closing, history ------------------------------------------------------


def _blocker(day: date, today: date, last: date | None, closed: bool) -> str | None:
    if closed:
        return "ALREADY_CLOSED"
    if day >= today:
        return "DAY_NOT_OVER"
    if last is not None and day <= last:
        return "ALREADY_CLOSED"
    if last is not None and day > last + timedelta(days=1):
        return "PREVIOUS_DAY_OPEN"
    return None


async def _closure(db: AsyncSession, hotel_id: uuid.UUID, day: date) -> DayClosure | None:
    return (
        await db.scalars(
            select(DayClosure).where(DayClosure.hotel_id == hotel_id, DayClosure.business_date == day)
        )
    ).one_or_none()


async def _closure_out(db: AsyncSession, closure: DayClosure) -> dict[str, Any]:
    name = (
        await db.scalar(select(User.full_name).where(User.id == closure.closed_by))
        if closure.closed_by
        else None
    )
    return {
        "id": closure.id,
        "date": closure.business_date,
        "closed_at": closure.closed_at,
        "closed_by_name": name,
        "notes": closure.notes,
        "open_items": _open_count(closure.open_items),
    }


async def overview(db: AsyncSession, ctx: HotelContext, day: date | None) -> dict[str, Any]:
    hotel = await _hotel(db, ctx.hotel_id)
    today = hotel.today()
    last = await last_closed(db, hotel.id)
    if day is None:
        day = (
            last + timedelta(days=1)
            if last is not None and last + timedelta(days=1) < today
            else today - timedelta(days=1)
        )
    closure = await _closure(db, hotel.id, day)
    if closure is not None:
        return {
            "date": day,
            "today": today,
            "last_closed": last,
            "can_close": False,
            "blocker": "ALREADY_CLOSED",
            "closure": await _closure_out(db, closure),
            "report": _hide_money(closure.report, ctx),
            "open_items": closure.open_items,
            "open_count": _open_count(closure.open_items),
        }
    items = await open_items(db, hotel, day)
    blocker = _blocker(day, today, last, closed=False)
    return {
        "date": day,
        "today": today,
        "last_closed": last,
        "can_close": blocker is None,
        "blocker": blocker,
        "closure": None,
        "report": _hide_money(_jsonable(await build_report(db, hotel, day)), ctx),
        "open_items": _jsonable(items),
        "open_count": _open_count(items),
    }


async def close_day(
    db: AsyncSession, ctx: HotelContext, day: date, *, notes: str | None, accept_open_items: bool
) -> dict[str, Any]:
    hotel = await _hotel(db, ctx.hotel_id)
    # One closure at a time per hotel (the order of days matters).
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"day-close:{hotel.id}"}
    )
    last = await last_closed(db, hotel.id)
    blocker = _blocker(day, hotel.today(), last, closed=await _closure(db, hotel.id, day) is not None)
    if blocker is not None:
        raise Conflict(
            blocker, params={"date": day.isoformat(), "last_closed": last.isoformat() if last else None}
        )
    items = await open_items(db, hotel, day)
    pending = _open_count(items)
    if pending and not accept_open_items:
        raise ValidationFailed(
            "OPEN_ITEMS",
            params={"count": pending},
            fields=[field_error("accept_open_items", "OPEN_ITEMS", count=pending)],
        )
    closure = DayClosure(
        id=uuid.uuid4(),
        hotel_id=hotel.id,
        business_date=day,
        closed_by=ctx.actor.user_id,
        report=_jsonable(await build_report(db, hotel, day)),
        open_items=_jsonable(items),
        notes=notes,
    )
    db.add(closure)
    await db.flush()
    audit.record(
        db,
        ctx.actor,
        "day.close",
        "day_closure",
        closure.id,
        hotel_id=hotel.id,
        changes={"date": [None, day.isoformat()], "open_items": [None, pending]},
    )
    await events.emit(
        db, hotel_id=hotel.id, entity="day_closure", action="created", entity_id=closure.id, actor=ctx.actor
    )
    await db.commit()
    return await overview(db, ctx, day)


async def history(db: AsyncSession, ctx: HotelContext, limit: int) -> list[dict[str, Any]]:
    closures = list(
        await db.scalars(
            select(DayClosure)
            .where(DayClosure.hotel_id == ctx.hotel_id)
            .order_by(DayClosure.business_date.desc())
            .limit(limit)
        )
    )
    out = []
    for c in closures:
        row = await _closure_out(db, c)
        rooms = c.report.get("rooms", {})
        row |= {
            "occupancy": rooms.get("occupancy"),
            "sold": rooms.get("sold"),
            "revenue": c.report.get("revenue", {}).get("total") if ctx.has(P.REPORTS_FINANCIAL) else None,
            "payments_net": c.report.get("payments_net") if ctx.has(P.PAYMENTS_VIEW) else None,
            "currency": c.report.get("currency"),
        }
        out.append(row)
    return out


async def closed_report(db: AsyncSession, ctx: HotelContext, day: date) -> tuple[Hotel, DayClosure]:
    hotel = await _hotel(db, ctx.hotel_id)
    closure = await _closure(db, hotel.id, day)
    if closure is None:
        raise NotFound("DAY_NOT_CLOSED")
    return hotel, closure
