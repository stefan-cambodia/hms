"""Company accounts (city ledger): see models.py for the money rules.

Every change to an account's money (a transfer, a payment received, a void)
locks the account row first, so credit-limit checks and allocations are made
one at a time per company.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit, crud, events, sequences
from app.core.context import HotelContext
from app.core.errors import Conflict, NotFound, ValidationFailed, field_error, register_constraint
from app.core.money import ZERO, round_money
from app.modules.accounts.models import AccountAllocation, AccountPayment, CompanyAccount
from app.modules.accounts.schemas import AccountIn, AccountPaymentIn, AccountUpdate, TransferIn
from app.modules.auth.models import User
from app.modules.billing import folio
from app.modules.billing import service as billing
from app.modules.billing.models import FOLIOS, Invoice, Payment
from app.modules.hotels.models import Hotel
from app.modules.nightaudit import lock
from app.modules.reservations.history import event, publish
from app.modules.reservations.models import Reservation

register_constraint("uq_company_accounts_hotel_id_code", "ACCOUNT_CODE_EXISTS", field="code")

FIELDS = (
    "code",
    "name",
    "legal_name",
    "tax_id",
    "address",
    "city",
    "country_code",
    "email",
    "phone",
    "contact_name",
    "language",
    "payment_terms_days",
    "credit_limit",
    "is_active",
    "notes",
)
TRANSFER_PREFIX = "CL-"


async def _hotel(db: AsyncSession, hotel_id: uuid.UUID) -> Hotel:
    hotel = await db.get(Hotel, hotel_id)
    assert hotel is not None
    return hotel


# --- balances ------------------------------------------------------------------------------

_LEDGER = text(
    """
    WITH paid AS (
        SELECT a.transfer_id, sum(a.amount) AS paid
        FROM account_allocations a JOIN account_payments ap ON ap.id = a.account_payment_id
        WHERE a.hotel_id = :hotel AND NOT ap.is_void
        GROUP BY a.transfer_id
    ),
    items AS (
        SELECT p.company_account_id AS account_id, p.amount_base AS amount, p.due_date,
               p.amount_base - coalesce(paid.paid, 0) AS open
        FROM payments p LEFT JOIN paid ON paid.transfer_id = p.id
        WHERE p.hotel_id = :hotel AND p.method = 'city_ledger' AND NOT p.is_void
    ),
    received AS (
        SELECT company_account_id AS account_id, sum(amount_base) AS total
        FROM account_payments WHERE hotel_id = :hotel AND NOT is_void
        GROUP BY company_account_id
    ),
    owed AS (
        SELECT account_id, sum(amount) AS transferred,
               sum(open) FILTER (WHERE open > 0 AND due_date < :today) AS overdue,
               count(*) FILTER (WHERE open > 0) AS open_items
        FROM items GROUP BY account_id
    )
    SELECT a.id, coalesce(o.transferred, 0) - coalesce(r.total, 0), coalesce(o.overdue, 0),
           coalesce(o.open_items, 0)
    FROM company_accounts a
    LEFT JOIN owed o ON o.account_id = a.id
    LEFT JOIN received r ON r.account_id = a.id
    WHERE a.hotel_id = :hotel
    """
)


async def balances(db: AsyncSession, hotel: Hotel) -> dict[uuid.UUID, tuple[Decimal, Decimal, int]]:
    """Per account: (balance owed, overdue, open items)."""
    rows = await db.execute(_LEDGER, {"hotel": hotel.id, "today": billing.hotel_today(hotel)})
    return {r[0]: (Decimal(r[1]), Decimal(r[2]), int(r[3])) for r in rows}


async def paid_on_transfer(db: AsyncSession, transfer_id: uuid.UUID) -> Decimal:
    return Decimal(
        await db.scalar(
            select(func.coalesce(func.sum(AccountAllocation.amount), 0))
            .join(AccountPayment, AccountPayment.id == AccountAllocation.account_payment_id)
            .where(AccountAllocation.transfer_id == transfer_id, AccountPayment.is_void.is_(False))
        )
    )


def account_out(acc: CompanyAccount, hotel: Hotel, figures: tuple[Decimal, Decimal, int] | None) -> dict:
    balance, overdue, open_items = figures or (ZERO, ZERO, 0)
    cur = hotel.currency_code
    return {
        **{f: getattr(acc, f) for f in (*FIELDS, "id", "version")},
        "currency": cur,
        "balance": round_money(balance, cur),
        "overdue": round_money(overdue, cur),
        "open_items": open_items,
    }


# --- accounts -------------------------------------------------------------------------------


async def list_accounts(
    db: AsyncSession, ctx: HotelContext, q: str | None, active: bool | None
) -> list[dict]:
    hotel = await _hotel(db, ctx.hotel_id)
    stmt = select(CompanyAccount).where(CompanyAccount.hotel_id == ctx.hotel_id)
    if active is not None:
        stmt = stmt.where(CompanyAccount.is_active.is_(active))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            CompanyAccount.name.ilike(like)
            | CompanyAccount.code.ilike(like)
            | CompanyAccount.tax_id.ilike(like)
        )
    accounts = list(await db.scalars(stmt.order_by(CompanyAccount.name)))
    figures = await balances(db, hotel)
    return [account_out(a, hotel, figures.get(a.id)) for a in accounts]


async def get_account(
    db: AsyncSession, hotel_id: uuid.UUID, account_id: uuid.UUID, *, lock_row: bool = False
):
    return await crud.get_scoped(
        db, CompanyAccount, hotel_id, account_id, code="ACCOUNT_NOT_FOUND", for_update=lock_row
    )


async def create_account(db: AsyncSession, ctx: HotelContext, data: AccountIn) -> CompanyAccount:
    acc = CompanyAccount(hotel_id=ctx.hotel_id, version=1, **data.model_dump())
    return await crud.create(db, ctx, acc, entity="company_account", fields=FIELDS)


async def update_account(
    db: AsyncSession, ctx: HotelContext, account_id: uuid.UUID, data: AccountUpdate
) -> CompanyAccount:
    acc = await get_account(db, ctx.hotel_id, account_id)
    changes = data.model_dump(exclude_unset=True, exclude={"version"})
    for required in ("name", "payment_terms_days", "is_active"):
        if required in changes and changes[required] is None:
            raise ValidationFailed(fields=[field_error(required, "REQUIRED")])
    return await crud.update(
        db, ctx, acc, changes, version=data.version, entity="company_account", fields=FIELDS
    )


async def delete_account(db: AsyncSession, ctx: HotelContext, account_id: uuid.UUID) -> None:
    """Only an account never used (no booking, transfer or payment); else deactivate it."""
    acc = await get_account(db, ctx.hotel_id, account_id)
    await crud.delete(db, ctx, acc, entity="company_account", fields=FIELDS)


# --- ledger ----------------------------------------------------------------------------------


async def _user_names(db: AsyncSession, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return {
        uid: name for uid, name in await db.execute(select(User.id, User.full_name).where(User.id.in_(ids)))
    }


_ITEMS = text(
    """
    SELECT p.id, p.number, p.invoice_id, i.number, p.reservation_id, r.code,
           trim(g.first_name || ' ' || g.last_name), p.received_at, p.due_date, p.amount_base, p.is_void,
           coalesce((SELECT sum(a.amount) FROM account_allocations a
                     JOIN account_payments ap ON ap.id = a.account_payment_id
                     WHERE a.transfer_id = p.id AND NOT ap.is_void), 0)
    FROM payments p
    JOIN invoices i ON i.id = p.invoice_id
    JOIN reservations r ON r.id = p.reservation_id
    JOIN guests g ON g.id = r.booker_guest_id
    WHERE p.company_account_id = :account AND p.method = 'city_ledger'
    ORDER BY p.received_at DESC
    """
)


async def detail(db: AsyncSession, ctx: HotelContext, account_id: uuid.UUID) -> dict:
    acc = await get_account(db, ctx.hotel_id, account_id)
    hotel = await _hotel(db, ctx.hotel_id)
    today = billing.hotel_today(hotel)
    items = []
    aging = {"current": ZERO, "days_1_30": ZERO, "days_31_60": ZERO, "days_61_90": ZERO, "days_over_90": ZERO}
    for row in await db.execute(_ITEMS, {"account": acc.id}):
        tid, number, inv_id, inv_number, res_id, code, guest, at, due, amount, is_void, paid = row
        open_amount = ZERO if is_void else Decimal(amount) - Decimal(paid)
        overdue_days = max((today - due).days, 0)
        if open_amount > ZERO:
            bucket = (
                "current"
                if overdue_days == 0
                else "days_1_30"
                if overdue_days <= 30
                else "days_31_60"
                if overdue_days <= 60
                else "days_61_90"
                if overdue_days <= 90
                else "days_over_90"
            )
            aging[bucket] += open_amount
        items.append(
            {
                "transfer_id": tid,
                "number": number,
                "invoice_id": inv_id,
                "invoice_number": inv_number,
                "reservation_id": res_id,
                "reservation_code": code,
                "guest_name": guest,
                "date": at.astimezone(hotel.zone).date(),
                "due_date": due,
                "amount": Decimal(amount),
                "paid": Decimal(paid),
                "open": open_amount,
                "days_overdue": overdue_days if open_amount > ZERO else 0,
                "is_void": is_void,
            }
        )
    invoice_numbers = {i["transfer_id"]: i["invoice_number"] for i in items}
    payments = list(
        await db.scalars(
            select(AccountPayment)
            .where(AccountPayment.company_account_id == acc.id)
            .order_by(AccountPayment.received_at.desc())
        )
    )
    allocations: dict[uuid.UUID, list[AccountAllocation]] = {}
    if payments:
        for a in await db.scalars(
            select(AccountAllocation).where(
                AccountAllocation.account_payment_id.in_([p.id for p in payments])
            )
        ):
            allocations.setdefault(a.account_payment_id, []).append(a)
    names = await _user_names(db, {p.received_by for p in payments})
    payment_rows = []
    for p in payments:
        allocs = allocations.get(p.id, [])
        payment_rows.append(
            {
                **{
                    f: getattr(p, f)
                    for f in (
                        "id",
                        "number",
                        "method",
                        "amount",
                        "currency",
                        "exchange_rate",
                        "amount_base",
                        "reference",
                        "notes",
                        "received_at",
                        "is_void",
                        "void_reason",
                    )
                },
                "received_by_name": names.get(p.received_by) if p.received_by else None,
                "allocations": [
                    {
                        "transfer_id": a.transfer_id,
                        "invoice_number": invoice_numbers.get(a.transfer_id, ""),
                        "amount": a.amount,
                    }
                    for a in allocs
                ],
                "unallocated": p.amount_base - sum((a.amount for a in allocs), ZERO),
            }
        )
    figures = (await balances(db, hotel)).get(acc.id)
    cur = hotel.currency_code
    for item in items:
        for key in ("amount", "paid", "open"):
            item[key] = round_money(item[key], cur)
    for row in payment_rows:
        row["unallocated"] = round_money(row["unallocated"], cur)
    aging = {k: round_money(v, cur) for k, v in aging.items()}
    return {**account_out(acc, hotel, figures), "aging": aging, "items": items, "payments": payment_rows}


# --- transfer of a folio to a company ---------------------------------------------------------


def company_bill_to(acc: CompanyAccount) -> dict[str, Any]:
    bill_to = {
        "company": acc.legal_name or acc.name,
        "name": acc.contact_name or acc.name,
        "address": acc.address,
        "city": acc.city,
        "country_code": acc.country_code,
        "tax_id": acc.tax_id,
        "email": acc.email,
        "company_account_id": str(acc.id),
    }
    return {k: v for k, v in bill_to.items() if v}


async def transfer(
    db: AsyncSession, ctx: HotelContext, res_id: uuid.UUID, data: TransferIn
) -> tuple[Reservation, Payment]:
    """Settle the folio's balance (the company's part of a split folio) by
    transferring it to the reservation's company account: the invoice is made
    out to the company (issued now if needed)."""
    res = await billing.load_reservation(db, ctx.hotel_id, res_id, for_update=True)
    if res.company_account_id is None:
        raise Conflict("NO_COMPANY_ACCOUNT", "The reservation is not authorised for direct billing")
    acc = await get_account(db, ctx.hotel_id, res.company_account_id, lock_row=True)
    if not acc.is_active:
        raise Conflict("ACCOUNT_INACTIVE")
    part = "company" if folio.is_split(res) else None
    st = await folio.statement(db, res, part)
    amount = st.totals.balance
    if amount <= ZERO:
        raise Conflict("NOTHING_TO_TRANSFER")
    hotel = await _hotel(db, ctx.hotel_id)
    owed = (await balances(db, hotel)).get(acc.id, (ZERO, ZERO, 0))[0]
    if acc.credit_limit is not None and owed + amount > acc.credit_limit:
        raise Conflict(
            "CREDIT_LIMIT_EXCEEDED",
            params={"limit": str(acc.credit_limit), "balance": str(owed), "amount": str(amount)},
        )
    inv = (
        await db.scalars(
            select(Invoice).where(
                Invoice.reservation_id == res.id,
                Invoice.status == "issued",
                Invoice.folio.in_(("all", part) if part else ("all", *FOLIOS)),
            )
        )
    ).first()
    if inv is None:
        inv = await billing.issue_invoice_tx(
            db, ctx, res, data.language or acc.language, company_bill_to(acc), part
        )
    elif inv.bill_to.get("company_account_id") != str(acc.id) or inv.folio != (part or "all"):
        # The company pays against an invoice made out to it: void this one first.
        raise Conflict("INVOICE_NOT_TO_COMPANY", params={"number": inv.number})
    elif billing.invoice_outdated(inv, st, {part: st.totals} if part else None):
        # Charges changed since it was issued: the company would owe more
        # (or less) than its invoice says.
        raise Conflict("INVOICE_OUTDATED", params={"number": inv.number})
    today = billing.hotel_today(hotel)
    payment = Payment(
        id=uuid.uuid4(),
        hotel_id=ctx.hotel_id,
        reservation_id=res.id,
        number=f"{TRANSFER_PREFIX}{await sequences.next_value(db, ctx.hotel_id, 'transfer'):06d}",
        kind="payment",
        method="city_ledger",
        amount=amount,
        currency=res.currency,
        exchange_rate=Decimal(1),
        amount_base=amount,
        company_account_id=acc.id,
        invoice_id=inv.id,
        due_date=today + timedelta(days=acc.payment_terms_days),
        received_at=datetime.now(UTC),
        received_by=ctx.actor.user_id,
        is_void=False,
        folio="company",
    )
    db.add(payment)
    await db.flush()
    await folio.recompute(db, res)
    billing._touch(res)
    await db.flush()
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
    audit.record(
        db,
        ctx.actor,
        "account.transfer",
        "company_account",
        acc.id,
        hotel_id=ctx.hotel_id,
        changes={"reservation": [None, res.code], "invoice": [None, inv.number], "amount": [None, amount]},
    )
    await publish(db, ctx, res, "updated", {"transfer": [None, f"{amount} {res.currency}"]})
    for entity, entity_id in (("payment", payment.id), ("company_account", acc.id)):
        await events.emit(
            db, hotel_id=ctx.hotel_id, entity=entity, action="created", entity_id=entity_id, actor=ctx.actor
        )
    await db.commit()
    return await billing.load_reservation(db, ctx.hotel_id, res_id), payment


# --- payments received from a company ----------------------------------------------------------


async def _open_items(db: AsyncSession, acc: CompanyAccount) -> list[tuple[uuid.UUID, Decimal]]:
    """Live transfers still owed, oldest due first."""
    rows = await db.execute(
        text(
            """
            SELECT p.id, p.amount_base - coalesce((
                SELECT sum(a.amount) FROM account_allocations a
                JOIN account_payments ap ON ap.id = a.account_payment_id
                WHERE a.transfer_id = p.id AND NOT ap.is_void), 0) AS open
            FROM payments p
            WHERE p.company_account_id = :account AND p.method = 'city_ledger' AND NOT p.is_void
            ORDER BY p.due_date, p.received_at
            """
        ),
        {"account": acc.id},
    )
    return [(tid, Decimal(open_)) for tid, open_ in rows if Decimal(open_) > ZERO]


async def receive_payment(
    db: AsyncSession, ctx: HotelContext, account_id: uuid.UUID, data: AccountPaymentIn
) -> AccountPayment:
    acc = await get_account(db, ctx.hotel_id, account_id, lock_row=True)
    hotel = await _hotel(db, ctx.hotel_id)
    currency = data.currency or hotel.currency_code
    rate = await billing.current_rate(db, hotel, currency)
    if data.exchange_rate is not None and data.exchange_rate != rate:
        raise Conflict("EXCHANGE_RATE_CHANGED", params={"currency": currency, "rate": str(rate)})
    amount_base = round_money(data.amount / rate, hotel.currency_code)
    if amount_base <= ZERO:
        raise ValidationFailed("AMOUNT_TOO_SMALL", fields=[field_error("amount", "AMOUNT_TOO_SMALL")])

    open_items = dict(await _open_items(db, acc))
    plan: list[tuple[uuid.UUID, Decimal]] = []
    if data.allocations is not None:
        for i, a in enumerate(data.allocations):
            if a.transfer_id not in open_items:
                raise ValidationFailed(
                    "NOT_AN_OPEN_ITEM",
                    fields=[field_error(f"allocations.{i}.transfer_id", "NOT_AN_OPEN_ITEM")],
                )
            if a.amount > open_items[a.transfer_id]:
                raise ValidationFailed(
                    "ALLOCATION_EXCEEDS_OPEN",
                    fields=[field_error(f"allocations.{i}.amount", "ALLOCATION_EXCEEDS_OPEN")],
                )
            plan.append((a.transfer_id, a.amount))
        if sum((amount for _, amount in plan), ZERO) > amount_base:
            raise ValidationFailed("ALLOCATIONS_EXCEED_PAYMENT")
    else:
        left = amount_base
        for tid, open_amount in open_items.items():
            if left <= ZERO:
                break
            take = min(left, open_amount)
            plan.append((tid, take))
            left -= take

    prefix = (hotel.billing_info or {}).get("receipt_prefix") or "RC-"
    payment = AccountPayment(
        id=uuid.uuid4(),
        hotel_id=ctx.hotel_id,
        company_account_id=acc.id,
        number=f"{prefix}{await sequences.next_value(db, ctx.hotel_id, 'receipt'):06d}",
        method=data.method,
        amount=data.amount,
        currency=currency,
        exchange_rate=rate,
        amount_base=amount_base,
        reference=data.reference,
        notes=data.notes,
        received_at=datetime.now(UTC),
        received_by=ctx.actor.user_id,
        is_void=False,
    )
    db.add(payment)
    await db.flush()
    db.add_all(
        AccountAllocation(
            hotel_id=ctx.hotel_id, account_payment_id=payment.id, transfer_id=tid, amount=amount
        )
        for tid, amount in plan
    )
    await db.flush()
    audit.record(
        db,
        ctx.actor,
        "account.payment",
        "company_account",
        acc.id,
        hotel_id=ctx.hotel_id,
        changes={"payment": [None, payment.number], "amount": [None, f"{payment.amount} {payment.currency}"]},
    )
    for entity, entity_id in (("company_account", acc.id), ("payment", payment.id)):
        await events.emit(
            db, hotel_id=ctx.hotel_id, entity=entity, action="created", entity_id=entity_id, actor=ctx.actor
        )
    await db.commit()
    return payment


async def void_payment(
    db: AsyncSession, ctx: HotelContext, account_id: uuid.UUID, payment_id: uuid.UUID, reason: str
) -> None:
    acc = await get_account(db, ctx.hotel_id, account_id, lock_row=True)
    payment = (
        await db.scalars(
            select(AccountPayment).where(
                AccountPayment.id == payment_id, AccountPayment.company_account_id == acc.id
            )
        )
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
    audit.record(
        db,
        ctx.actor,
        "account.payment_void",
        "company_account",
        acc.id,
        hotel_id=ctx.hotel_id,
        changes={"payment": [payment.number, None], "reason": [None, reason]},
    )
    for entity, entity_id in (("company_account", acc.id), ("payment", payment.id)):
        await events.emit(
            db, hotel_id=ctx.hotel_id, entity=entity, action="updated", entity_id=entity_id, actor=ctx.actor
        )
    await db.commit()


# --- reservations ------------------------------------------------------------------------------


async def check_assignable(db: AsyncSession, hotel_id: uuid.UUID, account_id: uuid.UUID) -> None:
    """A reservation can be authorised for direct billing to an active account."""
    acc = (
        await db.scalars(
            select(CompanyAccount).where(CompanyAccount.id == account_id, CompanyAccount.hotel_id == hotel_id)
        )
    ).one_or_none()
    if acc is None or not acc.is_active:
        raise ValidationFailed(fields=[field_error("company_account_id", "ACCOUNT_NOT_AVAILABLE")])


def due(today: date, terms: int) -> date:
    return today + timedelta(days=terms)
