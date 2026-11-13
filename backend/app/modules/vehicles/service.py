"""Vehicle rental.

Rental workflow: reserved → out (picked up) → returned; a reservation can be
cancelled, or marked no-show once its start has passed.

Price (fixed when booked, `rental_price`): the period is counted in started
hours; whole days at the daily rate, the remaining hours at the hourly rate
(never more than one day's rate), or a started day when there is no hourly
rate. A driver is charged per started day. A late return (beyond a grace of
GRACE_MINUTES) is charged as the price difference between the actual and the
planned period. Fuel and damage charges are added at return. Totals:

    subtotal = vehicle + driver + late fee + fuel + damage − discount
    total    = subtotal + service taxes (percent, inclusive or exclusive)

Safety: a vehicle in maintenance or retired, or whose insurance or
registration has expired, cannot be rented; a licence is required at pick-up
for motorised self-drive vehicles; a vehicle still out with a previous renter
cannot be handed over again.
"""

from __future__ import annotations

import math
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit, crud, events, sequences
from app.core.context import HotelContext
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed, field_error, register_constraint
from app.core.money import ZERO
from app.core.permissions import P
from app.core.security import encrypt_secret
from app.modules.auth.models import User
from app.modules.billing import folio, pos
from app.modules.guests import service as guests
from app.modules.guests.models import Guest
from app.modules.hotels.models import Hotel
from app.modules.nightaudit import lock
from app.modules.pricing import service as pricing
from app.modules.reservations import idempotency
from app.modules.reservations.models import Reservation, ReservationRoom
from app.modules.rooms.models import Room
from app.modules.vehicles.models import LICENCE_KINDS, Rental, RentalPayment, Vehicle

register_constraint("ex_vehicle_rentals_no_overlap", "VEHICLE_UNAVAILABLE")
register_constraint("uq_vehicles_hotel_id_code", "VEHICLE_CODE_EXISTS", field="code")
register_constraint("fk_vehicle_rentals_hotel_id_vehicles", "VEHICLE_IN_USE")

GRACE_MINUTES = 59
VEHICLE_FIELDS = (
    "code",
    "plate",
    "kind",
    "make",
    "model",
    "color",
    "year",
    "seats",
    "transmission",
    "daily_rate",
    "hourly_rate",
    "driver_daily_rate",
    "deposit_amount",
    "odometer",
    "status",
    "insurance_expiry",
    "registration_expiry",
    "notes",
    "sort_order",
)


async def _hotel(db: AsyncSession, hotel_id: uuid.UUID) -> Hotel:
    hotel = await db.get(Hotel, hotel_id)
    assert hotel is not None
    return hotel


def _require(ctx: HotelContext, permission: P) -> None:
    if not ctx.has(permission):
        raise Forbidden("PERMISSION_DENIED", params={"permission": permission})


# --- pricing -------------------------------------------------------------------------------


def rental_price(vehicle: Vehicle, start: datetime, end: datetime, with_driver: bool) -> dict[str, Any]:
    minutes = math.ceil((end - start).total_seconds() / 60)
    hours = max(1, math.ceil(minutes / 60))
    days, rest = divmod(hours, 24)
    if vehicle.hourly_rate is not None:
        base = vehicle.daily_rate * days + min(vehicle.hourly_rate * rest, vehicle.daily_rate)
    else:
        base = vehicle.daily_rate * (days + (1 if rest else 0))
    charge_days = days + (1 if rest else 0)
    driver = (vehicle.driver_daily_rate or ZERO) * charge_days if with_driver else ZERO
    return {"hours": hours, "charge_days": charge_days, "base_amount": base, "driver_amount": driver}


async def _taxes(db: AsyncSession, hotel: Hotel, subtotal: Decimal) -> tuple[list[dict], Decimal]:
    taxes = [t for t in await pricing.active_taxes(db, hotel.id, "services") if t.kind == "percent"]
    lines = folio.merge_tax_lines(
        folio.tax_line_dicts(pricing.compute_taxes(taxes, subtotal, 0, 0, hotel.currency_code))
    )
    return lines, sum((Decimal(t["amount"]) for t in lines if not t["is_inclusive"]), ZERO)


async def quote(
    db: AsyncSession,
    ctx: HotelContext,
    vehicle_id: uuid.UUID,
    start: datetime,
    end: datetime,
    with_driver: bool,
) -> dict[str, Any]:
    if end <= start:
        raise ValidationFailed("INVALID_DATES", fields=[field_error("end_at", "INVALID_DATES")])
    vehicle = await _vehicle(db, ctx.hotel_id, vehicle_id)
    _check_driver(vehicle, with_driver)
    hotel = await _hotel(db, ctx.hotel_id)
    price = rental_price(vehicle, start, end, with_driver)
    subtotal = price["base_amount"] + price["driver_amount"]
    lines, tax_total = await _taxes(db, hotel, subtotal)
    return {
        **price,
        "subtotal": subtotal,
        "tax_total": tax_total,
        "tax_breakdown": lines,
        "total": subtotal + tax_total,
        "deposit_amount": vehicle.deposit_amount,
    }


async def recompute(db: AsyncSession, rental: Rental) -> None:
    hotel = await _hotel(db, rental.hotel_id)
    rental.subtotal = max(
        rental.base_amount
        + rental.driver_amount
        + rental.late_fee
        + rental.fuel_charge
        + rental.damage_charge
        - rental.discount_amount,
        ZERO,
    )
    rental.tax_breakdown, rental.tax_total = await _taxes(db, hotel, rental.subtotal)
    rental.total = rental.subtotal + rental.tax_total
    rental.paid_total = sum(
        (
            p.amount_base
            for p in await db.scalars(select(RentalPayment).where(RentalPayment.rental_id == rental.id))
            if not p.is_void
        ),
        ZERO,
    )


# --- fleet ---------------------------------------------------------------------------------


async def _vehicle(db: AsyncSession, hotel_id: uuid.UUID, vehicle_id: uuid.UUID) -> Vehicle:
    return await crud.get_scoped(db, Vehicle, hotel_id, vehicle_id, code="VEHICLE_NOT_FOUND")


def _document_warning(vehicle: Vehicle, today: date) -> str | None:
    for field in ("insurance_expiry", "registration_expiry"):
        expiry = getattr(vehicle, field)
        if expiry and expiry < today:
            return f"{field}_expired"
    for field in ("insurance_expiry", "registration_expiry"):
        expiry = getattr(vehicle, field)
        if expiry and expiry <= today + timedelta(days=30):
            return f"{field}_soon"
    return None


def _check_rentable(vehicle: Vehicle, until: date) -> None:
    if vehicle.status != "available":
        raise Conflict("VEHICLE_NOT_AVAILABLE", params={"vehicle": vehicle.code, "status": vehicle.status})
    for field, code in (
        ("insurance_expiry", "INSURANCE_EXPIRED"),
        ("registration_expiry", "REGISTRATION_EXPIRED"),
    ):
        expiry = getattr(vehicle, field)
        if expiry and expiry < until:
            raise Conflict(code, params={"vehicle": vehicle.code, "date": expiry.isoformat()})


def _check_driver(vehicle: Vehicle, with_driver: bool) -> None:
    if with_driver and vehicle.driver_daily_rate is None:
        raise ValidationFailed("NO_DRIVER_SERVICE", fields=[field_error("with_driver", "NO_DRIVER_SERVICE")])


async def list_vehicles(
    db: AsyncSession, ctx: HotelContext, start: datetime | None, end: datetime | None
) -> list[dict[str, Any]]:
    hotel = await _hotel(db, ctx.hotel_id)
    today = hotel.today()
    vehicles = list(
        await db.scalars(
            select(Vehicle).where(Vehicle.hotel_id == ctx.hotel_id).order_by(Vehicle.sort_order, Vehicle.code)
        )
    )
    busy: set[uuid.UUID] = set()
    if start and end:
        busy = set(
            await db.scalars(
                select(Rental.vehicle_id).where(
                    Rental.hotel_id == ctx.hotel_id,
                    Rental.status.in_(("reserved", "out")),
                    Rental.period.op("&&")(func.tstzrange(start, end, "[)")),
                )
            )
        )
    out = []
    for v in vehicles:
        row = {f: getattr(v, f) for f in ("id", "version", *VEHICLE_FIELDS)}
        row["document_warning"] = _document_warning(v, today)
        if start and end:
            reason = None
            if v.status != "available":
                reason = v.status
            elif v.id in busy:
                reason = "booked"
            elif row["document_warning"] and row["document_warning"].endswith("_expired"):
                reason = "documents"
            row["available"], row["unavailable_reason"] = reason is None, reason
        out.append(row)
    return out


async def vehicle_out(db: AsyncSession, ctx: HotelContext, vehicle: Vehicle) -> dict[str, Any]:
    today = (await _hotel(db, ctx.hotel_id)).today()
    await db.refresh(vehicle)
    row = {f: getattr(vehicle, f) for f in ("id", "version", *VEHICLE_FIELDS)}
    row["document_warning"] = _document_warning(vehicle, today)
    return row


async def create_vehicle(db: AsyncSession, ctx: HotelContext, data: Any) -> Vehicle:
    obj = Vehicle(hotel_id=ctx.hotel_id, version=1, **data.model_dump())
    return await crud.create(db, ctx, obj, entity="vehicle", fields=VEHICLE_FIELDS)


async def update_vehicle(db: AsyncSession, ctx: HotelContext, vehicle_id: uuid.UUID, data: Any) -> Vehicle:
    obj = await _vehicle(db, ctx.hotel_id, vehicle_id)
    changes = data.model_dump(exclude_unset=True, exclude={"version"})
    return await crud.update(
        db, ctx, obj, changes, version=data.version, entity="vehicle", fields=VEHICLE_FIELDS
    )


async def delete_vehicle(db: AsyncSession, ctx: HotelContext, vehicle_id: uuid.UUID) -> None:
    obj = await _vehicle(db, ctx.hotel_id, vehicle_id)
    await crud.delete(db, ctx, obj, entity="vehicle", fields=VEHICLE_FIELDS)


# --- rentals ---------------------------------------------------------------------------------


async def get_rental(
    db: AsyncSession, hotel_id: uuid.UUID, rental_id: uuid.UUID, *, for_update: bool = False
) -> Rental:
    return await crud.get_scoped(
        db, Rental, hotel_id, rental_id, code="RENTAL_NOT_FOUND", for_update=for_update
    )


async def _publish(db: AsyncSession, ctx: HotelContext, rental: Rental, action: str, changes: dict) -> None:
    audit.record(
        db,
        ctx.actor,
        f"vehicle_rental.{action}",
        "vehicle_rental",
        rental.id,
        hotel_id=ctx.hotel_id,
        changes=changes,
    )
    await events.emit(
        db,
        hotel_id=ctx.hotel_id,
        entity="vehicle_rental",
        action="created" if action == "create" else "updated",
        entity_id=rental.id,
        version=rental.version,
        actor=ctx.actor,
    )


async def create_rental(
    db: AsyncSession, ctx: HotelContext, data: Any, idempotency_key: str | None
) -> Rental:
    digest = idempotency.digest("vehicle_rental", data.model_dump(mode="json"))
    if idempotency_key:
        previous = await idempotency.claim(db, ctx, idempotency_key, digest)
        if previous:
            return await get_rental(db, ctx.hotel_id, previous)
    vehicle = await _vehicle(db, ctx.hotel_id, data.vehicle_id)
    hotel = await _hotel(db, ctx.hotel_id)
    _check_rentable(vehicle, data.end_at.astimezone(hotel.zone).date())
    _check_driver(vehicle, data.with_driver)
    rr_id = data.reservation_room_id
    if rr_id:
        rr = (
            await db.scalars(
                select(ReservationRoom).where(
                    ReservationRoom.id == rr_id, ReservationRoom.hotel_id == ctx.hotel_id
                )
            )
        ).one_or_none()
        if rr is None:
            raise NotFound("RESERVATION_ROOM_NOT_FOUND")
        res = await db.get(Reservation, rr.reservation_id)
        assert res is not None
        guest_id = res.booker_guest_id
    elif data.guest_id:
        guest_id = (await crud.get_scoped(db, Guest, ctx.hotel_id, data.guest_id, code="GUEST_NOT_FOUND")).id
    else:
        guest_id = (await guests.create_guest(db, ctx, data.guest, commit=False)).id
    price = rental_price(vehicle, data.start_at, data.end_at, data.with_driver)
    rental = Rental(
        id=uuid.uuid4(),
        hotel_id=ctx.hotel_id,
        number=f"RNT-{await sequences.next_value(db, ctx.hotel_id, 'vehicle_rental'):06d}",
        vehicle_id=vehicle.id,
        guest_id=guest_id,
        reservation_room_id=rr_id,
        status="reserved",
        start_at=data.start_at,
        end_at=data.end_at,
        with_driver=data.with_driver,
        base_amount=price["base_amount"],
        driver_amount=price["driver_amount"],
        notes=data.notes,
        created_by=ctx.actor.user_id,
        version=1,
    )
    db.add(rental)
    await db.flush()  # exclusion constraint: the vehicle is free for this period
    await recompute(db, rental)
    await db.flush()
    if idempotency_key:
        await idempotency.bind(db, ctx, idempotency_key, rental.id)
    await _publish(
        db, ctx, rental, "create", {"number": [None, rental.number], "vehicle": [None, vehicle.code]}
    )
    await db.commit()
    return rental


async def update_rental(db: AsyncSession, ctx: HotelContext, rental_id: uuid.UUID, data: Any) -> Rental:
    """Extend or shorten the planned end (the vehicle price follows; the
    exclusion constraint refuses an extension over another rental)."""
    rental = await get_rental(db, ctx.hotel_id, rental_id, for_update=True)
    crud.check_version(rental, data.version)
    if rental.status not in ("reserved", "out"):
        raise Conflict("RENTAL_CLOSED", params={"status": rental.status})
    changes = data.model_dump(exclude_unset=True, exclude={"version"})
    old_end = rental.end_at
    if changes.get("end_at"):
        if changes["end_at"] <= rental.start_at:
            raise ValidationFailed("INVALID_DATES", fields=[field_error("end_at", "INVALID_DATES")])
        vehicle = await _vehicle(db, ctx.hotel_id, rental.vehicle_id)
        hotel = await _hotel(db, ctx.hotel_id)
        _check_rentable_documents(vehicle, changes["end_at"].astimezone(hotel.zone).date())
        rental.end_at = changes["end_at"]
        price = rental_price(vehicle, rental.start_at, rental.end_at, rental.with_driver)
        rental.base_amount, rental.driver_amount = price["base_amount"], price["driver_amount"]
    if "notes" in changes:
        rental.notes = changes["notes"]
    await db.flush()
    await recompute(db, rental)
    await db.flush()
    await _publish(db, ctx, rental, "update", {"end_at": [old_end, rental.end_at]})
    await db.commit()
    return rental


def _check_rentable_documents(vehicle: Vehicle, until: date) -> None:
    for field, code in (
        ("insurance_expiry", "INSURANCE_EXPIRED"),
        ("registration_expiry", "REGISTRATION_EXPIRED"),
    ):
        expiry = getattr(vehicle, field)
        if expiry and expiry < until:
            raise Conflict(code, params={"vehicle": vehicle.code, "date": expiry.isoformat()})


async def pickup(db: AsyncSession, ctx: HotelContext, rental_id: uuid.UUID, data: Any) -> Rental:
    rental = await get_rental(db, ctx.hotel_id, rental_id, for_update=True)
    crud.check_version(rental, data.version)
    if rental.status != "reserved":
        raise Conflict("INVALID_STATUS_TRANSITION", params={"from": rental.status, "to": "out"})
    vehicle = await crud.get_scoped(
        db, Vehicle, ctx.hotel_id, rental.vehicle_id, code="VEHICLE_NOT_FOUND", for_update=True
    )
    hotel = await _hotel(db, ctx.hotel_id)
    now = datetime.now(UTC)
    if now < rental.start_at - timedelta(hours=2):
        raise Conflict("PICKUP_TOO_EARLY", params={"start": rental.start_at.isoformat()})
    _check_rentable(vehicle, rental.end_at.astimezone(hotel.zone).date())
    still_out = await db.scalar(
        select(Rental.number).where(
            Rental.vehicle_id == vehicle.id, Rental.status == "out", Rental.id != rental.id
        )
    )
    if still_out:
        raise Conflict("VEHICLE_NOT_RETURNED", params={"vehicle": vehicle.code, "rental": still_out})
    if vehicle.kind in LICENCE_KINDS and not rental.with_driver:
        if not data.licence_number:
            raise ValidationFailed(
                "LICENCE_REQUIRED", fields=[field_error("licence_number", "LICENCE_REQUIRED")]
            )
        if data.licence_expiry and data.licence_expiry < rental.end_at.astimezone(hotel.zone).date():
            raise ValidationFailed(
                "LICENCE_EXPIRED", fields=[field_error("licence_expiry", "LICENCE_EXPIRED")]
            )
    if data.odometer_out < vehicle.odometer:
        raise ValidationFailed(
            "ODOMETER_BELOW_RECORDED",
            params={"odometer": vehicle.odometer},
            fields=[field_error("odometer_out", "ODOMETER_BELOW_RECORDED")],
        )
    if data.licence_number:
        rental.licence_number = encrypt_secret(data.licence_number)
        rental.licence_last4 = data.licence_number[-4:]
    rental.licence_country = data.licence_country
    rental.licence_expiry = data.licence_expiry
    rental.odometer_out, rental.fuel_out, rental.condition_out = (
        data.odometer_out,
        data.fuel_out,
        data.condition_out,
    )
    rental.deposit_kind = data.deposit_kind
    if data.deposit_kind in ("cash", "card_hold"):
        rental.deposit_amount = (
            data.deposit_amount if data.deposit_amount is not None else vehicle.deposit_amount
        )
        rental.deposit_currency = data.deposit_currency or hotel.currency_code
    rental.deposit_note = data.deposit_note
    rental.status = "out"
    rental.picked_up_at = now
    if now < rental.start_at:
        # Handed over early (allowed up to 2 h): the rental starts now; the
        # booked price stays, and late fees compare against the same start.
        rental.start_at = now
    vehicle.odometer = data.odometer_out
    await db.flush()
    await _publish(
        db, ctx, rental, "pickup", {"status": ["reserved", "out"], "odometer": [None, data.odometer_out]}
    )
    await db.commit()
    return rental


async def return_vehicle(db: AsyncSession, ctx: HotelContext, rental_id: uuid.UUID, data: Any) -> Rental:
    rental = await get_rental(db, ctx.hotel_id, rental_id, for_update=True)
    crud.check_version(rental, data.version)
    if rental.status != "out":
        raise Conflict("INVALID_STATUS_TRANSITION", params={"from": rental.status, "to": "returned"})
    vehicle = await crud.get_scoped(
        db, Vehicle, ctx.hotel_id, rental.vehicle_id, code="VEHICLE_NOT_FOUND", for_update=True
    )
    now = datetime.now(UTC)
    returned_at = data.returned_at or now
    if returned_at > now + timedelta(minutes=5) or (
        rental.picked_up_at and returned_at < rental.picked_up_at
    ):
        raise ValidationFailed(
            "INVALID_RETURN_TIME", fields=[field_error("returned_at", "INVALID_RETURN_TIME")]
        )
    if rental.odometer_out is not None and data.odometer_in < rental.odometer_out:
        raise ValidationFailed(
            "ODOMETER_BELOW_RECORDED",
            params={"odometer": rental.odometer_out},
            fields=[field_error("odometer_in", "ODOMETER_BELOW_RECORDED")],
        )
    if data.waive_late_fee:
        _require(ctx, P.VEHICLES_MANAGE)  # waiving money owed needs a manager
    late = ZERO
    # The first GRACE_MINUTES of any extra time are free, also for the rounding
    # to started hours: late = price(start → return − grace) − planned price.
    effective_end = returned_at - timedelta(minutes=GRACE_MINUTES)
    if effective_end > rental.end_at and not data.waive_late_fee:
        actual = rental_price(vehicle, rental.start_at, effective_end, rental.with_driver)
        planned = rental_price(vehicle, rental.start_at, rental.end_at, rental.with_driver)
        late = max(
            actual["base_amount"]
            + actual["driver_amount"]
            - planned["base_amount"]
            - planned["driver_amount"],
            ZERO,
        )
    rental.status = "returned"
    rental.returned_at = returned_at
    rental.odometer_in, rental.fuel_in, rental.condition_in = (
        data.odometer_in,
        data.fuel_in,
        data.condition_in,
    )
    rental.late_fee = late
    rental.fuel_charge = data.fuel_charge
    rental.damage_charge = data.damage_charge
    rental.damage_note = data.damage_note
    if data.deposit_returned and rental.deposit_kind != "none":
        rental.deposit_returned_at = now
    vehicle.odometer = max(vehicle.odometer, data.odometer_in)
    if data.vehicle_needs_maintenance:
        vehicle.status = "maintenance"
    await db.flush()
    await recompute(db, rental)
    await db.flush()
    await _publish(
        db,
        ctx,
        rental,
        "return",
        {"status": ["out", "returned"], "late_fee": [None, late], "damage": [None, data.damage_charge]},
    )
    if data.vehicle_needs_maintenance:
        await events.emit(
            db,
            hotel_id=ctx.hotel_id,
            entity="vehicle",
            action="updated",
            entity_id=vehicle.id,
            actor=ctx.actor,
        )
    await db.commit()
    return rental


async def return_deposit(db: AsyncSession, ctx: HotelContext, rental_id: uuid.UUID, version: int) -> Rental:
    rental = await get_rental(db, ctx.hotel_id, rental_id, for_update=True)
    crud.check_version(rental, version)
    if rental.deposit_kind == "none" or rental.deposit_returned_at:
        raise Conflict("NO_DEPOSIT_HELD")
    rental.deposit_returned_at = datetime.now(UTC)
    await db.flush()
    await _publish(db, ctx, rental, "deposit_returned", {"deposit": [rental.deposit_kind, "returned"]})
    await db.commit()
    return rental


async def set_discount(db: AsyncSession, ctx: HotelContext, rental_id: uuid.UUID, data: Any) -> Rental:
    _require(ctx, P.VEHICLES_MANAGE)
    rental = await get_rental(db, ctx.hotel_id, rental_id, for_update=True)
    crud.check_version(rental, data.version)
    if rental.status in ("cancelled", "no_show"):
        raise Conflict("RENTAL_CLOSED", params={"status": rental.status})
    if data.amount and not data.reason:
        raise ValidationFailed("REASON_REQUIRED", fields=[field_error("reason", "REASON_REQUIRED")])
    rental.discount_amount = data.amount
    rental.discount_reason = data.reason if data.amount else None
    await recompute(db, rental)
    if rental.paid_total > rental.total:
        raise Conflict("DISCOUNT_BELOW_PAID")
    await db.flush()
    await _publish(db, ctx, rental, "discount", {"discount": [None, str(data.amount)]})
    await db.commit()
    return rental


async def close_unused(
    db: AsyncSession, ctx: HotelContext, rental_id: uuid.UUID, status: str, data: Any
) -> Rental:
    """Cancel a reservation, or mark a no-show once the start has passed."""
    rental = await get_rental(db, ctx.hotel_id, rental_id, for_update=True)
    crud.check_version(rental, data.version)
    if rental.status != "reserved":
        raise Conflict("INVALID_STATUS_TRANSITION", params={"from": rental.status, "to": status})
    if status == "no_show" and datetime.now(UTC) < rental.start_at:
        raise Conflict("NO_SHOW_BEFORE_START")
    if rental.paid_total > ZERO:
        raise Conflict("RENTAL_HAS_PAYMENTS")
    rental.status = status
    rental.cancel_reason = getattr(data, "reason", None)
    # Nothing is owed for an unused rental (fees can be agreed as a discount-free payment).
    rental.base_amount = rental.driver_amount = ZERO
    await recompute(db, rental)
    await db.flush()
    await _publish(db, ctx, rental, status, {"status": ["reserved", status]})
    await db.commit()
    return rental


# --- payments --------------------------------------------------------------------------------


async def record_payment(
    db: AsyncSession, ctx: HotelContext, rental_id: uuid.UUID, data: Any, idempotency_key: str | None
) -> tuple[Rental, Decimal | None]:
    digest = idempotency.digest(f"rental-payment:{rental_id}", data.model_dump(mode="json"))
    if idempotency_key and await idempotency.claim(db, ctx, idempotency_key, digest):
        return await get_rental(db, ctx.hotel_id, rental_id), None
    rental = await get_rental(db, ctx.hotel_id, rental_id, for_update=True)
    if rental.status in ("cancelled", "no_show"):
        raise Conflict("RENTAL_CLOSED", params={"status": rental.status})
    await recompute(db, rental)
    balance = rental.total - rental.paid_total
    if balance <= ZERO:
        raise Conflict("NOTHING_TO_PAY")
    hotel = await _hotel(db, ctx.hotel_id)
    now = datetime.now(UTC)
    change = None
    if data.method == "room_charge":
        if rental.status != "returned":
            raise Conflict("ROOM_CHARGE_AFTER_RETURN")  # the final amount is known at return
        if rental.paid_total != ZERO:
            raise Conflict("ROOM_CHARGE_FULL_ONLY")
        rr_id = data.reservation_room_id or rental.reservation_room_id
        if rr_id is None:
            raise ValidationFailed(
                "ROOM_REQUIRED", fields=[field_error("reservation_room_id", "ROOM_REQUIRED")]
            )
        rr = await pos.in_house_stay(db, ctx.hotel_id, rr_id)
        from app.modules.billing.documents import labels

        name = {lang: labels(lang)["vehicle_rental"] for lang in ("en", "fr", "zh-CN", "ru", "km")}
        charge = await pos.charge_to_room(
            db,
            ctx,
            rr,
            name=name,
            reference=rental.number,
            total=rental.total,
            tax_total=rental.tax_total,
            tax_lines=rental.tax_breakdown,
            service_date=(rental.returned_at or now).astimezone(hotel.zone).date(),
        )
        payment = RentalPayment(
            id=uuid.uuid4(),
            hotel_id=ctx.hotel_id,
            rental_id=rental.id,
            method="room_charge",
            amount=balance,
            currency=hotel.currency_code,
            exchange_rate=Decimal(1),
            amount_base=balance,
            reservation_room_id=rr.id,
            folio_charge_id=charge.id,
            received_at=now,
            received_by=ctx.actor.user_id,
            is_void=False,
        )
    else:
        t = await pos.tender(db, hotel, balance, data)
        change = t.change
        payment = RentalPayment(
            id=uuid.uuid4(),
            hotel_id=ctx.hotel_id,
            rental_id=rental.id,
            method=data.method,
            amount=t.amount,
            currency=t.currency,
            exchange_rate=t.exchange_rate,
            amount_base=t.amount_base,
            tendered=t.tendered,
            reference=data.reference,
            card_brand=data.card_brand,
            card_last4=data.card_last4,
            received_at=now,
            received_by=ctx.actor.user_id,
            is_void=False,
        )
    db.add(payment)
    await db.flush()
    await recompute(db, rental)
    rental.updated_at = now
    await db.flush()
    if idempotency_key:
        await idempotency.bind(db, ctx, idempotency_key, rental.id)
    await _publish(
        db,
        ctx,
        rental,
        "payment",
        {"payment": [None, f"{payment.method} {payment.amount} {payment.currency}"]},
    )
    await events.emit(
        db, hotel_id=ctx.hotel_id, entity="payment", action="created", entity_id=payment.id, actor=ctx.actor
    )
    await db.commit()
    return rental, change


async def void_payment(
    db: AsyncSession, ctx: HotelContext, rental_id: uuid.UUID, payment_id: uuid.UUID, reason: str
) -> Rental:
    _require(ctx, P.VEHICLES_MANAGE)
    rental = await get_rental(db, ctx.hotel_id, rental_id, for_update=True)
    payment = (
        await db.scalars(
            select(RentalPayment).where(RentalPayment.id == payment_id, RentalPayment.rental_id == rental.id)
        )
    ).one_or_none()
    if payment is None:
        raise NotFound("PAYMENT_NOT_FOUND")
    if payment.is_void:
        raise Conflict("ALREADY_VOID")
    hotel = await db.get(Hotel, ctx.hotel_id)
    assert hotel is not None
    await lock.ensure_received_on_open_day(db, ctx.hotel_id, payment.received_at, hotel.timezone)
    if payment.folio_charge_id:
        await pos.void_room_charge(db, ctx, payment.folio_charge_id, f"{rental.number}: {reason}")
    now = datetime.now(UTC)
    payment.is_void, payment.void_reason, payment.voided_at, payment.voided_by = (
        True,
        reason,
        now,
        ctx.actor.user_id,
    )
    await db.flush()
    await recompute(db, rental)
    rental.updated_at = now
    await db.flush()
    await _publish(
        db,
        ctx,
        rental,
        "void_payment",
        {"payment": [str(payment.amount_base), None], "reason": [None, reason]},
    )
    await db.commit()
    return rental


# --- read model ------------------------------------------------------------------------------


async def rentals_out(
    db: AsyncSession, rentals: list[Rental], *, with_payments: bool = False
) -> list[dict[str, Any]]:
    if not rentals:
        return []
    now = datetime.now(UTC)
    vehicles = {
        v.id: v
        for v in await db.scalars(select(Vehicle).where(Vehicle.id.in_({r.vehicle_id for r in rentals})))
    }
    guest_rows = {
        g.id: g for g in await db.scalars(select(Guest).where(Guest.id.in_({r.guest_id for r in rentals})))
    }
    rr_ids = {r.reservation_room_id for r in rentals if r.reservation_room_id}
    stays = {}
    if rr_ids:
        for rr, room in (
            await db.execute(
                select(ReservationRoom, Room)
                .outerjoin(Room, Room.id == ReservationRoom.room_id)
                .where(ReservationRoom.id.in_(rr_ids))
            )
        ).all():
            stays[rr.id] = (rr, room)
    out = []
    for r in rentals:
        v = vehicles[r.vehicle_id]
        g = guest_rows[r.guest_id]
        stay = stays.get(r.reservation_room_id) if r.reservation_room_id else None
        label = " ".join(x for x in (v.make, v.model) if x) or v.code
        row = {
            f: getattr(r, f)
            for f in (
                "id",
                "number",
                "vehicle_id",
                "guest_id",
                "reservation_room_id",
                "status",
                "start_at",
                "end_at",
                "picked_up_at",
                "returned_at",
                "with_driver",
                "licence_last4",
                "licence_country",
                "licence_expiry",
                "odometer_out",
                "odometer_in",
                "fuel_out",
                "fuel_in",
                "condition_out",
                "condition_in",
                "deposit_kind",
                "deposit_amount",
                "deposit_currency",
                "deposit_note",
                "deposit_returned_at",
                "base_amount",
                "driver_amount",
                "late_fee",
                "fuel_charge",
                "damage_charge",
                "damage_note",
                "discount_amount",
                "discount_reason",
                "subtotal",
                "tax_total",
                "tax_breakdown",
                "total",
                "paid_total",
                "notes",
                "cancel_reason",
                "created_at",
                "version",
            )
        }
        row.update(
            vehicle_code=v.code,
            vehicle_label=f"{v.code} · {label}" + (f" · {v.plate}" if v.plate else ""),
            vehicle_kind=v.kind,
            vehicle_odometer=v.odometer,
            guest_name=f"{g.first_name} {g.last_name}".strip(),
            guest_phone=g.phone,
            room_number=stay[1].number if stay and stay[1] else None,
            in_house=bool(stay and stay[0].checked_in_at and not stay[0].checked_out_at),
            overdue=r.status == "out" and r.end_at < now,
            licence_required=v.kind in LICENCE_KINDS and not r.with_driver,
            balance=r.total - r.paid_total,
        )
        out.append(row)
    if with_payments:
        payments = list(
            await db.scalars(
                select(RentalPayment)
                .where(RentalPayment.rental_id.in_([r.id for r in rentals]))
                .order_by(RentalPayment.received_at)
            )
        )
        names = (
            {
                u.id: u.full_name
                for u in await db.scalars(
                    select(User).where(User.id.in_({p.received_by for p in payments if p.received_by}))
                )
            }
            if payments
            else {}
        )
        rooms = {}
        pay_rr = {p.reservation_room_id for p in payments if p.reservation_room_id}
        if pay_rr:
            for rr, room in (
                await db.execute(
                    select(ReservationRoom, Room)
                    .outerjoin(Room, Room.id == ReservationRoom.room_id)
                    .where(ReservationRoom.id.in_(pay_rr))
                )
            ).all():
                rooms[rr.id] = room.number if room else None
        for row in out:
            row["payments"] = [
                {
                    **{
                        f: getattr(p, f)
                        for f in (
                            "id",
                            "method",
                            "amount",
                            "currency",
                            "exchange_rate",
                            "amount_base",
                            "tendered",
                            "reference",
                            "card_brand",
                            "card_last4",
                            "received_at",
                            "is_void",
                            "void_reason",
                        )
                    },
                    "room_number": rooms.get(p.reservation_room_id) if p.reservation_room_id else None,
                    "received_by_name": names.get(p.received_by) if p.received_by else None,
                }
                for p in payments
                if p.rental_id == row["id"]
            ]
    return out


async def rental_out(db: AsyncSession, rental: Rental, change_due: Decimal | None = None) -> dict[str, Any]:
    await db.refresh(rental)
    row = (await rentals_out(db, [rental], with_payments=True))[0]
    row["change_due"] = change_due
    return row


async def list_rentals(
    db: AsyncSession,
    ctx: HotelContext,
    *,
    status: str | None,
    start: datetime | None,
    end: datetime | None,
    vehicle_id: uuid.UUID | None,
) -> list[dict[str, Any]]:
    stmt = select(Rental).where(Rental.hotel_id == ctx.hotel_id)
    if status == "active":
        stmt = stmt.where(Rental.status.in_(("reserved", "out")))
    elif status:
        stmt = stmt.where(Rental.status == status)
    if start and end:
        stmt = stmt.where(Rental.period.op("&&")(func.tstzrange(start, end, "[)")))
    if vehicle_id:
        stmt = stmt.where(Rental.vehicle_id == vehicle_id)
    return await rentals_out(db, list(await db.scalars(stmt.order_by(Rental.start_at).limit(500))))


# --- contract PDF ----------------------------------------------------------------------------


async def contract_pdf(
    db: AsyncSession, ctx: HotelContext, rental_id: uuid.UUID, language: str | None
) -> tuple[bytes, str]:
    from app.modules.billing import documents, pdf

    rental = await get_rental(db, ctx.hotel_id, rental_id)
    hotel = await _hotel(db, ctx.hotel_id)
    row = (await rentals_out(db, [rental], with_payments=True))[0]
    guest = await db.get(Guest, rental.guest_id)
    lang = documents.pick_language(language, guest, hotel)
    tr = documents.Tr(lang, hotel.default_language)
    cur = hotel.currency_code
    when = lambda dt: tr.datetime(dt, hotel.timezone) if dt else "—"  # noqa: E731
    meta = [
        [tr("vehicle"), f"{row['vehicle_label']} ({tr('vehicle_kinds.' + row['vehicle_kind'])})"],
        [tr("rental_period"), f"{when(rental.start_at)} – {when(rental.end_at)}"],
    ]

    def handover(at: datetime, km: int | None, fuel: int | None) -> str:
        return f"{when(at)} · {km} km · {tr('fuel_eighths', n='—' if fuel is None else fuel)}"

    if rental.picked_up_at:
        meta.append([tr("picked_up"), handover(rental.picked_up_at, rental.odometer_out, rental.fuel_out)])
    if rental.returned_at:
        meta.append([tr("returned"), handover(rental.returned_at, rental.odometer_in, rental.fuel_in)])
    if rental.licence_last4:
        meta.append(
            [
                tr("licence"),
                f"•••• {rental.licence_last4}"
                + (f" ({rental.licence_country})" if rental.licence_country else ""),
            ]
        )
    if rental.deposit_kind != "none":
        deposit = tr("deposit_kinds." + rental.deposit_kind)
        if rental.deposit_amount:
            deposit += f" {tr.money(rental.deposit_amount, rental.deposit_currency or cur)}"
        if rental.deposit_returned_at:
            deposit += f" · {tr('deposit_returned')}"
        meta.append([tr("deposit"), deposit])
    lines = []
    price = rental_price(
        await _vehicle(db, ctx.hotel_id, rental.vehicle_id),
        rental.start_at,
        rental.end_at,
        rental.with_driver,
    )
    if rental.base_amount:
        lines.append(
            _line(
                tr("vehicle_rental"),
                tr("rental_duration", days=price["charge_days"], hours=price["hours"]),
                1,
                rental.base_amount,
                tr,
                cur,
            )
        )
    if rental.driver_amount:
        days = max(price["charge_days"], 1)
        lines.append(_line(tr("driver"), "", days, rental.driver_amount / days, tr, cur))
    for amount, label, detail in (
        (rental.late_fee, tr("late_return"), ""),
        (rental.fuel_charge, tr("fuel_charge"), ""),
        (rental.damage_charge, tr("fee.damage"), rental.damage_note or ""),
    ):
        if amount:
            lines.append(_line(label, detail, 1, amount, tr, cur))
    totals: list[list[Any]] = [
        [tr("subtotal"), tr.money(rental.subtotal + rental.discount_amount, cur), False]
    ]
    if rental.discount_amount:
        totals.append([tr("discount"), tr.money(-rental.discount_amount, cur), False])
    for t in rental.tax_breakdown:
        name = (tr.text(t.get("name")) or t["code"]) + f" {tr.number(Decimal(t['rate']))}%"
        totals.append(
            [
                tr("tax_included", name=name) if t["is_inclusive"] else name,
                tr.money(Decimal(t["amount"]), cur),
                False,
            ]
        )
    totals.append([tr("total"), tr.money(rental.total, cur), True])
    totals.append([tr("paid"), tr.money(rental.paid_total, cur), False])
    if rental.total - rental.paid_total > 0:
        totals.append([tr("balance_due"), tr.money(rental.total - rental.paid_total, cur), True])
    doc = {
        "kind": "rental",
        "language": lang,
        "title": tr("title.rental_contract"),
        "number": rental.number,
        "issue_date": tr.date(rental.start_at.astimezone(hotel.zone).date()),
        "hotel": await documents.hotel_block(db, hotel, tr),
        "bill_to_label": tr("renter"),
        "bill_to": [
            x
            for x in (
                row["guest_name"],
                row["guest_phone"],
                tr("room_number", number=row["room_number"]) if row["room_number"] else None,
            )
            if x
        ],
        "meta": meta,
        "page_css": documents._page_css(tr("page_of", page="\x00page", pages="\x00pages")),
        "labels": {
            k: tr(k)
            for k in (
                "number",
                "issue_date",
                "description",
                "quantity",
                "unit_price",
                "amount",
                "payments",
                "void_stamp",
            )
        },
        "lines": lines,
        "totals": totals,
        "payments": [
            {
                "date": tr.date(p["received_at"].astimezone(hotel.zone).date()),
                "number": "",
                "label": tr("room_charge", room=p["room_number"] or "—")
                if p["method"] == "room_charge"
                else tr("method." + p["method"]),
                "amount": tr.money(p["amount_base"], cur),
            }
            for p in row["payments"]
            if not p["is_void"]
        ],
        "notes": [tr("rental_terms")],
        "signatures": [tr("signature_renter"), tr("signature_hotel")],
        "is_void": rental.status in ("cancelled", "no_show"),
    }
    return await pdf.render_pdf(db, doc), rental.number


def _line(description: str, detail: str, quantity: int, unit: Decimal, tr: Any, cur: str) -> dict[str, Any]:
    return {
        "description": description,
        "detail": detail,
        "quantity": str(quantity),
        "unit_price": tr.money(unit, cur),
        "amount": tr.money(unit * quantity, cur),
        "void": False,
    }
