"""Folio charges, payments, invoices and accepted currencies.

All folio operations lock the reservation row (SELECT ... FOR UPDATE) so that
concurrent postings from several desks serialise and the stored totals stay
exact. Every change recomputes the folio, writes a reservation event, an audit
record and a real-time notification in the same transaction.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import audit, crud, events, sequences
from app.core.context import HotelContext
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed, field_error, register_constraint
from app.core.money import ZERO, round_money
from app.core.permissions import P
from app.modules.auth.models import User
from app.modules.billing import folio
from app.modules.billing.models import Currency, FolioCharge, Invoice, Payment
from app.modules.billing.schemas import (
    ChargeIn,
    ChargeOut,
    CurrencyIn,
    CurrencyUpdate,
    FolioOut,
    FolioTotals,
    InvoiceOut,
    IssueInvoiceIn,
    PaymentIn,
    PaymentOut,
)
from app.modules.facilities.models import Service
from app.modules.guests.models import Guest
from app.modules.hotels.models import Hotel
from app.modules.nightaudit import lock
from app.modules.pricing import service as pricing
from app.modules.reservations import idempotency
from app.modules.reservations.history import event, publish
from app.modules.reservations.models import Reservation, ReservationRoom

register_constraint("uq_currencies_hotel_id_code", "CURRENCY_EXISTS", field="code")
register_constraint("uq_invoices_one_issued_per_reservation", "INVOICE_ALREADY_ISSUED")
register_constraint("financial_row_immutable", "FINANCIAL_RECORD_IMMUTABLE")
register_constraint("fk_folio_charges_hotel_id_services", "SERVICE_IN_USE")

CLOSED = {"checked_out", "cancelled", "no_show"}


def hotel_today(hotel: Hotel) -> date:
    return hotel.today()


async def load_reservation(
    db: AsyncSession, hotel_id: uuid.UUID, res_id: uuid.UUID, *, for_update: bool = False
) -> Reservation:
    """A reservation with its stays and nights; optionally row-locked."""
    stmt = (
        select(Reservation)
        .where(Reservation.id == res_id, Reservation.hotel_id == hotel_id)
        .options(selectinload(Reservation.rooms).selectinload(ReservationRoom.nights))
        .execution_options(populate_existing=True)
    )
    if for_update:
        stmt = stmt.with_for_update(of=Reservation)
    res = (await db.scalars(stmt)).one_or_none()
    if res is None:
        raise NotFound("RESERVATION_NOT_FOUND")
    return res


async def _hotel(db: AsyncSession, hotel_id: uuid.UUID) -> Hotel:
    hotel = await db.get(Hotel, hotel_id)
    assert hotel is not None
    return hotel


def _touch(res: Reservation) -> None:
    res.updated_at = datetime.now(UTC)


# --- currencies --------------------------------------------------------------------

CURRENCY_FIELDS = ("code", "units_per_base", "is_active")


async def list_currencies(db: AsyncSession, hotel_id: uuid.UUID) -> list[Currency]:
    return list(
        await db.scalars(select(Currency).where(Currency.hotel_id == hotel_id).order_by(Currency.code))
    )


async def create_currency(db: AsyncSession, ctx: HotelContext, data: CurrencyIn) -> Currency:
    hotel = await _hotel(db, ctx.hotel_id)
    if data.code == hotel.currency_code:
        raise ValidationFailed("BASE_CURRENCY", fields=[field_error("code", "BASE_CURRENCY")])
    from app.core.refdata import is_currency

    if not is_currency(data.code):
        raise ValidationFailed("INVALID_CURRENCY", fields=[field_error("code", "INVALID_CURRENCY")])
    obj = Currency(hotel_id=ctx.hotel_id, version=1, **data.model_dump())
    return await crud.create(db, ctx, obj, entity="currency", fields=CURRENCY_FIELDS)


async def update_currency(
    db: AsyncSession, ctx: HotelContext, currency_id: uuid.UUID, data: CurrencyUpdate
) -> Currency:
    obj = await crud.get_scoped(db, Currency, ctx.hotel_id, currency_id, code="CURRENCY_NOT_FOUND")
    changes = data.model_dump(exclude_unset=True, exclude={"version"})
    return await crud.update(
        db, ctx, obj, changes, version=data.version, entity="currency", fields=CURRENCY_FIELDS
    )


async def delete_currency(db: AsyncSession, ctx: HotelContext, currency_id: uuid.UUID) -> None:
    # Payments keep the currency code and rate they used, so removing an
    # accepted currency never alters past payments.
    obj = await crud.get_scoped(db, Currency, ctx.hotel_id, currency_id, code="CURRENCY_NOT_FOUND")
    await crud.delete(db, ctx, obj, entity="currency", fields=CURRENCY_FIELDS)


async def current_rate(db: AsyncSession, hotel: Hotel, code: str) -> Decimal:
    """Units of `code` per 1 unit of the hotel currency."""
    if code == hotel.currency_code:
        return Decimal(1)
    row = (
        await db.scalars(
            select(Currency).where(
                Currency.hotel_id == hotel.id, Currency.code == code, Currency.is_active.is_(True)
            )
        )
    ).one_or_none()
    if row is None:
        raise ValidationFailed(
            "CURRENCY_NOT_ACCEPTED",
            params={"currency": code},
            fields=[field_error("currency", "CURRENCY_NOT_ACCEPTED")],
        )
    return row.units_per_base


# --- folio read model --------------------------------------------------------------


async def _user_names(db: AsyncSession, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    return {u.id: u.full_name for u in await db.scalars(select(User).where(User.id.in_(wanted)))}


def invoice_out(inv: Invoice) -> InvoiceOut:
    return InvoiceOut(
        **{f: getattr(inv, f) for f in InvoiceOut.model_fields if f != "balance"},
        balance=inv.total - inv.paid_total,
    )


async def folio_out(db: AsyncSession, res: Reservation) -> FolioOut:
    st = await folio.statement(db, res)
    names = await _user_names(
        db,
        {c.created_by for c in st.charges}
        | {c.voided_by for c in st.charges}
        | {p.received_by for p in st.payments}
        | {p.voided_by for p in st.payments},
    )
    charges = [
        ChargeOut.model_validate(c).model_copy(
            update={"created_by_name": names.get(c.created_by), "voided_by_name": names.get(c.voided_by)}
        )
        for c in st.charges
    ]
    payments = [
        PaymentOut.model_validate(p).model_copy(
            update={"received_by_name": names.get(p.received_by), "voided_by_name": names.get(p.voided_by)}
        )
        for p in st.payments
    ]
    active = next((i for i in st.invoices if i.status == "issued"), None)
    return FolioOut(
        reservation_id=res.id,
        version=res.version,
        currency=res.currency,
        accommodation=[run.__dict__ for run in st.accommodation],
        charges=charges,
        payments=payments,
        taxes=res.tax_breakdown,
        totals=FolioTotals(
            accommodation=res.accommodation_total,
            charges=res.charges_total,
            tax_total=res.tax_total,
            grand_total=res.grand_total,
            paid_total=res.paid_total,
            balance=st.balance,
        ),
        invoices=[invoice_out(i) for i in st.invoices],
        invoice_outdated=bool(
            active and (active.total != res.grand_total or active.paid_total != res.paid_total)
        ),
    )


# --- charges -----------------------------------------------------------------------


def _require(ctx: HotelContext, permission: P) -> None:
    if not ctx.has(permission):
        raise Forbidden("PERMISSION_DENIED", params={"permission": permission})


async def _service_taxes(db: AsyncSession, hotel_id: uuid.UUID, amount: Decimal, currency: str) -> list[dict]:
    # Only percentage taxes apply to services (per-night taxes are accommodation taxes).
    taxes = [t for t in await pricing.active_taxes(db, hotel_id, "services") if t.kind == "percent"]
    return folio.merge_tax_lines(folio.tax_line_dicts(pricing.compute_taxes(taxes, amount, 0, 0, currency)))


async def build_charge(
    db: AsyncSession, ctx: HotelContext, res: Reservation, data: ChargeIn, hotel: Hotel
) -> FolioCharge:
    """Validate and price a charge (not yet added to the session)."""
    if data.reservation_room_id and data.reservation_room_id not in {rr.id for rr in res.rooms}:
        raise NotFound("RESERVATION_ROOM_NOT_FOUND")
    name: dict[str, str] = {}
    unit_price = data.unit_price
    if data.service_id:
        service = await crud.get_scoped(db, Service, ctx.hotel_id, data.service_id, code="SERVICE_NOT_FOUND")
        if not service.is_active:
            raise ValidationFailed("SERVICE_INACTIVE", fields=[field_error("service_id", "SERVICE_INACTIVE")])
        name = dict(service.name)
        if unit_price is None:
            unit_price = service.price
    assert unit_price is not None
    amount = round_money(data.quantity * unit_price, res.currency)
    if data.kind == "adjustment" and amount == ZERO:
        raise ValidationFailed("AMOUNT_REQUIRED", fields=[field_error("unit_price", "AMOUNT_REQUIRED")])
    taxes = await _service_taxes(db, ctx.hotel_id, amount, res.currency) if data.kind == "service" else []
    return FolioCharge(
        id=uuid.uuid4(),
        hotel_id=ctx.hotel_id,
        reservation_id=res.id,
        reservation_room_id=data.reservation_room_id,
        kind=data.kind,
        fee_type=data.fee_type,
        service_id=data.service_id,
        name=name,
        description=data.description,
        service_date=data.service_date or hotel_today(hotel),
        quantity=data.quantity,
        unit_price=unit_price,
        amount=amount,
        tax_amount=sum((Decimal(t["amount"]) for t in taxes if not t["is_inclusive"]), ZERO),
        tax_breakdown=taxes,
        is_void=False,
        created_by=ctx.actor.user_id,
    )


async def add_charge(
    db: AsyncSession, ctx: HotelContext, res: Reservation, data: ChargeIn, *, system: bool = False
) -> FolioCharge:
    """Post a charge inside the caller's transaction (also used for automatic
    cancellation / no-show fees, with system=True)."""
    hotel = await _hotel(db, ctx.hotel_id)
    charge = await build_charge(db, ctx, res, data, hotel)
    db.add(charge)
    await db.flush()
    await folio.recompute(db, res)
    _touch(res)
    await db.flush()
    event(
        db,
        ctx,
        res,
        "charge_posted",
        charge_id=charge.id,
        kind=charge.kind,
        fee_type=charge.fee_type,
        name=charge.name,
        description=charge.description,
        quantity=charge.quantity,
        amount=charge.amount,
        automatic=system,
    )
    return charge


async def post_charge(
    db: AsyncSession, ctx: HotelContext, res_id: uuid.UUID, data: ChargeIn, idempotency_key: str | None
) -> Reservation:
    if data.kind == "adjustment":
        _require(ctx, P.FOLIO_ADJUST)
    digest = idempotency.digest(f"charge:{res_id}", data.model_dump(mode="json"))
    if idempotency_key and await idempotency.claim(db, ctx, idempotency_key, digest):
        return await load_reservation(db, ctx.hotel_id, res_id)
    res = await load_reservation(db, ctx.hotel_id, res_id, for_update=True)
    if res.status in CLOSED:
        # Late charges (e.g. minibar found after departure) need a supervisor.
        _require(ctx, P.FOLIO_ADJUST)
    hotel = await _hotel(db, ctx.hotel_id)
    await lock.ensure_open(db, ctx.hotel_id, data.service_date or hotel_today(hotel))
    charge = await add_charge(db, ctx, res, data)
    if idempotency_key:
        await idempotency.bind(db, ctx, idempotency_key, charge.id)
    await publish(db, ctx, res, "updated", {"charge": [None, str(charge.amount)]})
    await db.commit()
    return await load_reservation(db, ctx.hotel_id, res_id)


async def void_charge_tx(
    db: AsyncSession, ctx: HotelContext, res: Reservation, charge: FolioCharge, reason: str
) -> None:
    """Void a charge inside the caller's transaction (reservation row locked)."""
    if charge.is_void:
        raise Conflict("ALREADY_VOID")
    charge.is_void = True
    charge.void_reason = reason
    charge.voided_at = datetime.now(UTC)
    charge.voided_by = ctx.actor.user_id
    await db.flush()
    await folio.recompute(db, res)
    _touch(res)
    await db.flush()
    event(db, ctx, res, "charge_voided", charge_id=charge.id, amount=charge.amount, reason=reason)
    await publish(db, ctx, res, "updated", {"charge_void": [str(charge.amount), None]})


async def void_charge(
    db: AsyncSession, ctx: HotelContext, res_id: uuid.UUID, charge_id: uuid.UUID, reason: str
) -> Reservation:
    res = await load_reservation(db, ctx.hotel_id, res_id, for_update=True)
    charge = (
        await db.scalars(
            select(FolioCharge).where(FolioCharge.id == charge_id, FolioCharge.reservation_id == res.id)
        )
    ).one_or_none()
    if charge is None:
        raise NotFound("CHARGE_NOT_FOUND")
    if charge.kind == "outlet":
        # A restaurant check charged to the room is voided from the restaurant,
        # so the check and the folio always agree.
        raise Conflict("VOID_FROM_OUTLET")
    await lock.ensure_open(db, ctx.hotel_id, charge.service_date)
    await void_charge_tx(db, ctx, res, charge, reason)
    await db.commit()
    return await load_reservation(db, ctx.hotel_id, res_id)


async def post_outlet_charge(
    db: AsyncSession,
    ctx: HotelContext,
    res: Reservation,
    *,
    reservation_room_id: uuid.UUID,
    name: dict[str, str],
    description: str,
    net_amount: Decimal,
    tax_lines: list[dict[str, Any]],
    service_date: date,
) -> FolioCharge:
    """Post a restaurant/bar check to a guest folio inside the caller's
    transaction. The amount is net of exclusive taxes and the check's own tax
    lines are kept, so the folio adds exactly the check total and the invoice
    shows the right tax amounts (no second taxation)."""
    charge = FolioCharge(
        id=uuid.uuid4(),
        hotel_id=ctx.hotel_id,
        reservation_id=res.id,
        reservation_room_id=reservation_room_id,
        kind="outlet",
        name=name,
        description=description,
        service_date=service_date,
        quantity=Decimal(1),
        unit_price=net_amount,
        amount=net_amount,
        tax_amount=sum((Decimal(t["amount"]) for t in tax_lines if not t["is_inclusive"]), ZERO),
        tax_breakdown=tax_lines,
        is_void=False,
        created_by=ctx.actor.user_id,
    )
    db.add(charge)
    await db.flush()
    await folio.recompute(db, res)
    _touch(res)
    await db.flush()
    event(
        db,
        ctx,
        res,
        "charge_posted",
        charge_id=charge.id,
        kind="outlet",
        fee_type=None,
        name=name,
        description=description,
        quantity=1,
        amount=net_amount + charge.tax_amount,
        automatic=False,
    )
    await publish(db, ctx, res, "updated", {"charge": [None, str(net_amount + charge.tax_amount)]})
    return charge


# --- payments ----------------------------------------------------------------------


async def record_payment(
    db: AsyncSession, ctx: HotelContext, res_id: uuid.UUID, data: PaymentIn, idempotency_key: str | None
) -> tuple[Reservation, Payment]:
    if data.kind == "refund":
        _require(ctx, P.PAYMENTS_REFUND)
    digest = idempotency.digest(f"payment:{res_id}", data.model_dump(mode="json"))
    if idempotency_key:
        previous = await idempotency.claim(db, ctx, idempotency_key, digest)
        if previous:
            payment = await db.get(Payment, previous)
            assert payment is not None
            return await load_reservation(db, ctx.hotel_id, res_id), payment
    res = await load_reservation(db, ctx.hotel_id, res_id, for_update=True)
    hotel = await _hotel(db, ctx.hotel_id)
    currency = data.currency or res.currency
    rate = await current_rate(db, hotel, currency)
    if data.exchange_rate is not None and data.exchange_rate != rate:
        raise Conflict("EXCHANGE_RATE_CHANGED", params={"currency": currency, "rate": str(rate)})
    amount_base = round_money(data.amount / rate, res.currency)
    if amount_base <= ZERO:
        raise ValidationFailed("AMOUNT_TOO_SMALL", fields=[field_error("amount", "AMOUNT_TOO_SMALL")])
    if data.kind == "refund" and amount_base > res.paid_total:
        raise Conflict("REFUND_EXCEEDS_PAID", params={"max": str(max(res.paid_total, ZERO))})
    prefix = (hotel.billing_info or {}).get("receipt_prefix") or "RC-"
    payment = Payment(
        id=uuid.uuid4(),
        hotel_id=ctx.hotel_id,
        reservation_id=res.id,
        number=f"{prefix}{await sequences.next_value(db, ctx.hotel_id, 'receipt'):06d}",
        kind=data.kind,
        method=data.method,
        amount=data.amount,
        currency=currency,
        exchange_rate=rate,
        amount_base=amount_base,
        reference=data.reference,
        card_brand=data.card_brand,
        card_last4=data.card_last4,
        notes=data.notes,
        received_at=datetime.now(UTC),
        received_by=ctx.actor.user_id,
        is_void=False,
    )
    db.add(payment)
    await db.flush()
    await folio.recompute(db, res)
    _touch(res)
    await db.flush()
    if idempotency_key:
        await idempotency.bind(db, ctx, idempotency_key, payment.id)
    event(
        db,
        ctx,
        res,
        "payment_recorded",
        payment_id=payment.id,
        number=payment.number,
        kind=payment.kind,
        method=payment.method,
        amount=payment.amount,
        currency=payment.currency,
        amount_base=payment.amount_base,
    )
    await publish(db, ctx, res, "updated", {"payment": [None, f"{payment.amount} {payment.currency}"]})
    await events.emit(
        db, hotel_id=ctx.hotel_id, entity="payment", action="created", entity_id=payment.id, actor=ctx.actor
    )
    await db.commit()
    return await load_reservation(db, ctx.hotel_id, res_id), payment


async def void_payment(
    db: AsyncSession, ctx: HotelContext, res_id: uuid.UUID, payment_id: uuid.UUID, reason: str
) -> Reservation:
    res = await load_reservation(db, ctx.hotel_id, res_id, for_update=True)
    payment = (
        await db.scalars(select(Payment).where(Payment.id == payment_id, Payment.reservation_id == res.id))
    ).one_or_none()
    if payment is None:
        raise NotFound("PAYMENT_NOT_FOUND")
    if payment.is_void:
        raise Conflict("ALREADY_VOID")
    hotel = await _hotel(db, ctx.hotel_id)
    await lock.ensure_received_on_open_day(db, ctx.hotel_id, payment.received_at, hotel.timezone)
    payment.is_void = True
    payment.void_reason = reason
    payment.voided_at = datetime.now(UTC)
    payment.voided_by = ctx.actor.user_id
    await db.flush()
    await folio.recompute(db, res)
    _touch(res)
    await db.flush()
    event(db, ctx, res, "payment_voided", payment_id=payment.id, number=payment.number, reason=reason)
    await publish(db, ctx, res, "updated", {"payment_void": [payment.number, None]})
    await events.emit(
        db, hotel_id=ctx.hotel_id, entity="payment", action="updated", entity_id=payment.id, actor=ctx.actor
    )
    await db.commit()
    return await load_reservation(db, ctx.hotel_id, res_id)


def _period(stmt: Select, column: Any, start: date | None, end: date | None, tz: str) -> Select:
    """Filter a timestamp column on hotel-local dates [start, end] (inclusive)."""
    zone = ZoneInfo(tz)
    if start:
        stmt = stmt.where(column >= datetime.combine(start, datetime.min.time(), zone))
    if end:
        stmt = stmt.where(column < datetime.combine(end + timedelta(days=1), datetime.min.time(), zone))
    return stmt


async def list_payments(
    db: AsyncSession,
    ctx: HotelContext,
    *,
    start: date | None,
    end: date | None,
    method: str | None,
    currency: str | None,
    include_void: bool,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    hotel = await _hotel(db, ctx.hotel_id)
    base = (
        select(Payment, Reservation.code, Guest.first_name, Guest.last_name)
        .join(Reservation, Reservation.id == Payment.reservation_id)
        .join(Guest, Guest.id == Reservation.booker_guest_id)
        .where(Payment.hotel_id == ctx.hotel_id)
    )
    base = _period(base, Payment.received_at, start, end, hotel.timezone)
    if method:
        base = base.where(Payment.method == method)
    if currency:
        base = base.where(Payment.currency == currency)
    listed = base if include_void else base.where(Payment.is_void.is_(False))
    total = await db.scalar(select(func.count()).select_from(listed.order_by(None).subquery()))
    rows = (await db.execute(listed.order_by(Payment.received_at.desc()).limit(limit).offset(offset))).all()
    names = await _user_names(db, {r[0].received_by for r in rows} | {r[0].voided_by for r in rows})
    items = [
        {
            **PaymentOut.model_validate(p).model_dump(),
            "received_by_name": names.get(p.received_by),
            "voided_by_name": names.get(p.voided_by),
            "reservation_id": p.reservation_id,
            "reservation_code": code,
            "guest_name": f"{first} {last}".strip(),
        }
        for p, code, first, last in rows
    ]
    # Totals per method / currency / kind over the whole period (voids excluded).
    sub = base.where(Payment.is_void.is_(False)).subquery()
    summary_rows = (
        await db.execute(
            select(
                sub.c.method,
                sub.c.currency,
                sub.c.kind,
                func.count(),
                func.sum(sub.c.amount),
                func.sum(sub.c.amount_base),
            )
            .group_by(sub.c.method, sub.c.currency, sub.c.kind)
            .order_by(sub.c.method, sub.c.currency, sub.c.kind)
        )
    ).all()
    summary = [
        {"method": m, "currency": c, "kind": k, "count": n, "amount": a, "amount_base": b}
        for m, c, k, n, a, b in summary_rows
    ]
    net = sum((-r["amount_base"] if r["kind"] == "refund" else r["amount_base"] for r in summary), ZERO)
    return {
        "items": items,
        "total": int(total or 0),
        "limit": limit,
        "offset": offset,
        "summary": summary,
        "net_base": net,
    }


# --- invoices ----------------------------------------------------------------------


async def issue_invoice(
    db: AsyncSession, ctx: HotelContext, res_id: uuid.UUID, data: IssueInvoiceIn
) -> Invoice:
    from app.modules.billing import documents

    res = await load_reservation(db, ctx.hotel_id, res_id, for_update=True)
    existing = await db.scalar(
        select(func.count()).where(Invoice.reservation_id == res.id, Invoice.status == "issued")
    )
    if existing:
        raise Conflict("INVOICE_ALREADY_ISSUED")
    if res.grand_total <= ZERO:
        raise Conflict("NOTHING_TO_INVOICE")
    hotel = await _hotel(db, ctx.hotel_id)
    guest = await db.get(Guest, res.booker_guest_id)
    assert guest is not None
    language = documents.pick_language(data.language, guest, hotel)
    bill_to = data.bill_to.model_dump(exclude_none=True) if data.bill_to else documents.guest_bill_to(guest)
    prefix = (hotel.billing_info or {}).get("invoice_prefix") or "INV-"
    number = f"{prefix}{await sequences.next_value(db, ctx.hotel_id, 'invoice'):06d}"
    issue_date = hotel_today(hotel)
    st = await folio.statement(db, res)
    document = await documents.build(
        db, "invoice", language, hotel, st, bill_to=bill_to, number=number, issue_date=issue_date
    )
    inv = Invoice(
        id=uuid.uuid4(),
        hotel_id=ctx.hotel_id,
        reservation_id=res.id,
        number=number,
        status="issued",
        issue_date=issue_date,
        language=language,
        currency=res.currency,
        bill_to=bill_to,
        document=document,
        subtotal=res.accommodation_total + res.charges_total,
        tax_total=res.tax_total,
        total=res.grand_total,
        paid_total=res.paid_total,
        created_by=ctx.actor.user_id,
    )
    db.add(inv)
    await db.flush()
    event(
        db, ctx, res, "invoice_issued", invoice_id=inv.id, number=number, total=inv.total, language=language
    )
    audit.record(
        db,
        ctx.actor,
        "invoice.issue",
        "invoice",
        inv.id,
        hotel_id=ctx.hotel_id,
        changes={"number": [None, number], "total": [None, inv.total], "reservation": [None, res.code]},
    )
    await events.emit(
        db, hotel_id=ctx.hotel_id, entity="invoice", action="created", entity_id=inv.id, actor=ctx.actor
    )
    await events.emit(
        db,
        hotel_id=ctx.hotel_id,
        entity="reservation",
        action="updated",
        entity_id=res.id,
        version=res.version,
        actor=ctx.actor,
    )
    await db.commit()
    return inv


async def get_invoice(db: AsyncSession, hotel_id: uuid.UUID, invoice_id: uuid.UUID) -> Invoice:
    return await crud.get_scoped(db, Invoice, hotel_id, invoice_id, code="INVOICE_NOT_FOUND")


async def void_invoice(db: AsyncSession, ctx: HotelContext, invoice_id: uuid.UUID, reason: str) -> Invoice:
    inv = await crud.get_scoped(
        db, Invoice, ctx.hotel_id, invoice_id, code="INVOICE_NOT_FOUND", for_update=True
    )
    if inv.status == "void":
        raise Conflict("ALREADY_VOID")
    res = await load_reservation(db, ctx.hotel_id, inv.reservation_id)
    inv.status = "void"
    inv.void_reason = reason
    inv.voided_at = datetime.now(UTC)
    inv.voided_by = ctx.actor.user_id
    await db.flush()
    event(db, ctx, res, "invoice_voided", invoice_id=inv.id, number=inv.number, reason=reason)
    audit.record(
        db,
        ctx.actor,
        "invoice.void",
        "invoice",
        inv.id,
        hotel_id=ctx.hotel_id,
        changes={"status": ["issued", "void"], "reason": [None, reason]},
    )
    await events.emit(
        db, hotel_id=ctx.hotel_id, entity="invoice", action="updated", entity_id=inv.id, actor=ctx.actor
    )
    await events.emit(
        db,
        hotel_id=ctx.hotel_id,
        entity="reservation",
        action="updated",
        entity_id=res.id,
        version=res.version,
        actor=ctx.actor,
    )
    await db.commit()
    return inv


async def list_invoices(
    db: AsyncSession,
    ctx: HotelContext,
    *,
    q: str | None,
    status: str | None,
    start: date | None,
    end: date | None,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    stmt = (
        select(Invoice, Reservation.code)
        .join(Reservation, Reservation.id == Invoice.reservation_id)
        .where(Invoice.hotel_id == ctx.hotel_id)
    )
    if status:
        stmt = stmt.where(Invoice.status == status)
    if start:
        stmt = stmt.where(Invoice.issue_date >= start)
    if end:
        stmt = stmt.where(Invoice.issue_date <= end)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Invoice.number.ilike(like),
                Reservation.code.ilike(like),
                Invoice.bill_to["name"].astext.ilike(like),
                Invoice.bill_to["company"].astext.ilike(like),
            )
        )
    total = await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = (await db.execute(stmt.order_by(Invoice.number.desc()).limit(limit).offset(offset))).all()
    return [{**invoice_out(inv).model_dump(), "reservation_code": code} for inv, code in rows], int(
        total or 0
    )


# --- PDF documents -----------------------------------------------------------------


async def invoice_pdf(db: AsyncSession, hotel_id: uuid.UUID, invoice_id: uuid.UUID) -> tuple[bytes, str]:
    from app.modules.billing import pdf

    inv = await get_invoice(db, hotel_id, invoice_id)
    return await pdf.render_pdf(db, inv.document, void=inv.status == "void"), inv.number


async def statement_pdf(
    db: AsyncSession, hotel_id: uuid.UUID, res_id: uuid.UUID, language: str | None
) -> tuple[bytes, str]:
    from app.modules.billing import documents, pdf

    res = await load_reservation(db, hotel_id, res_id)
    hotel = await _hotel(db, hotel_id)
    guest = await db.get(Guest, res.booker_guest_id)
    assert guest is not None
    doc = await documents.build(
        db,
        "statement",
        documents.pick_language(language, guest, hotel),
        hotel,
        await folio.statement(db, res),
        bill_to=documents.guest_bill_to(guest),
        issue_date=hotel_today(hotel),
    )
    return await pdf.render_pdf(db, doc), f"folio-{res.code}"


async def receipt_pdf(
    db: AsyncSession, hotel_id: uuid.UUID, res_id: uuid.UUID, payment_id: uuid.UUID, language: str | None
) -> tuple[bytes, str]:
    from app.modules.billing import documents, pdf

    res = await load_reservation(db, hotel_id, res_id)
    payment = (
        await db.scalars(select(Payment).where(Payment.id == payment_id, Payment.reservation_id == res.id))
    ).one_or_none()
    if payment is None:
        raise NotFound("PAYMENT_NOT_FOUND")
    hotel = await _hotel(db, hotel_id)
    guest = await db.get(Guest, res.booker_guest_id)
    assert guest is not None
    doc = await documents.build(
        db,
        "receipt",
        documents.pick_language(language, guest, hotel),
        hotel,
        await folio.statement(db, res),
        bill_to=documents.guest_bill_to(guest),
        number=payment.number,
        issue_date=payment.received_at.astimezone(hotel.zone).date(),
        payment=payment,
    )
    return await pdf.render_pdf(db, doc), payment.number
