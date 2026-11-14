"""The guest folio: the single place where a reservation's money is computed.

    grand_total = accommodation (fixed nightly prices of live stays)
                + extra charges (services, fees, adjustments; voids excluded)
                + exclusive taxes (accommodation taxes + taxes of service charges)
    paid_total  = payments + deposits - refunds (voids excluded), in hotel currency
    balance     = grand_total - paid_total   (> 0: guest owes; < 0: refund due)

Every code path that changes nights, charges or payments calls `recompute()`
in the same transaction, so stored totals always match their parts.

Split folio (billed to a company that pays the room only): the company's part
holds the nights, their taxes and the room fees (cancellation, no-show, early
departure, late check-out); the guest's part holds every other charge. A
charge can be moved to the other part by hand. Each payment belongs to one
part, and the two parts always add up to the reservation's totals.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.money import ZERO
from app.modules.billing.models import FolioCharge, Invoice, Payment
from app.modules.pricing import service as pricing
from app.modules.reservations.models import Reservation, ReservationRoom

# Room fees: paid by the company when only the room is billed to it.
ROOM_FEES = frozenset({"cancellation", "no_show", "early_departure", "late_checkout"})


def is_split(res: Reservation) -> bool:
    return res.company_account_id is not None and res.company_pays == "room"


def charge_folio(c: FolioCharge) -> str:
    """The part of a split folio a charge belongs to."""
    if c.folio:
        return c.folio
    return "company" if c.kind == "fee" and c.fee_type in ROOM_FEES else "guest"


def tax_line_dicts(lines: list[pricing.TaxLine]) -> list[dict[str, Any]]:
    return [
        {
            "code": t.code,
            "name": t.name,
            "kind": t.kind,
            "rate": str(t.rate),
            "is_inclusive": t.is_inclusive,
            "amount": str(t.amount),
        }
        for t in lines
    ]


def merge_tax_lines(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sum tax lines by (code, inclusive); zero lines are dropped."""
    merged: dict[tuple[str, bool], dict[str, Any]] = {}
    for group in groups:
        for line in group:
            key = (line["code"], bool(line["is_inclusive"]))
            if key in merged:
                merged[key]["amount"] = str(Decimal(merged[key]["amount"]) + Decimal(line["amount"]))
            else:
                merged[key] = dict(line)
    return [line for line in merged.values() if Decimal(line["amount"]) != ZERO]


def subtract_tax_lines(total: list[dict[str, Any]], part: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`total` minus `part`, line by line (zero lines dropped)."""
    negated = [{**line, "amount": str(-Decimal(line["amount"]))} for line in part]
    return merge_tax_lines([dict(line) for line in total], negated)


async def charges_of(db: AsyncSession, res_id: uuid.UUID, *, include_void: bool = False) -> list[FolioCharge]:
    stmt = select(FolioCharge).where(FolioCharge.reservation_id == res_id)
    if not include_void:
        stmt = stmt.where(FolioCharge.is_void.is_(False))
    return list(await db.scalars(stmt.order_by(FolioCharge.service_date, FolioCharge.created_at)))


async def payments_of(db: AsyncSession, res_id: uuid.UUID, *, include_void: bool = False) -> list[Payment]:
    stmt = select(Payment).where(Payment.reservation_id == res_id)
    if not include_void:
        stmt = stmt.where(Payment.is_void.is_(False))
    return list(await db.scalars(stmt.order_by(Payment.received_at)))


def signed_base(p: Payment) -> Decimal:
    return -p.amount_base if p.kind == "refund" else p.amount_base


async def recompute(db: AsyncSession, res: Reservation) -> None:
    """Recompute and store every total of a reservation from its parts."""
    live = [rr for rr in res.rooms if rr.occupies_inventory]
    accommodation = sum((rr.accommodation_total for rr in live), ZERO)
    room_nights = sum(len(rr.nights) for rr in live)
    person_nights = sum(len(rr.nights) * (rr.adults + rr.children) for rr in live)
    accommodation_taxes = pricing.compute_taxes(
        await pricing.active_taxes(db, res.hotel_id, "accommodation"),
        accommodation,
        room_nights,
        person_nights,
        res.currency,
    )
    charges = await charges_of(db, res.id)
    payments = await payments_of(db, res.id)
    taxes = merge_tax_lines(tax_line_dicts(accommodation_taxes), *(c.tax_breakdown for c in charges))

    res.accommodation_total = accommodation
    res.charges_total = sum((c.amount for c in charges), ZERO)
    res.tax_breakdown = taxes
    res.tax_total = sum((Decimal(t["amount"]) for t in taxes if not t["is_inclusive"]), ZERO)
    res.grand_total = res.accommodation_total + res.charges_total + res.tax_total
    res.paid_total = sum((signed_base(p) for p in payments), ZERO)
    res.adults = sum(rr.adults for rr in res.rooms) or 1
    res.children = sum(rr.children for rr in res.rooms)
    stays = live or res.rooms
    res.arrival = min(rr.arrival for rr in stays)
    res.departure = max(rr.departure for rr in stays)


# --- statement (what the folio screen and the PDFs show) ----------------------


@dataclass(frozen=True)
class AccommodationRun:
    """Consecutive nights of one stay at the same price."""

    reservation_room_id: uuid.UUID
    room_type_id: uuid.UUID
    room_id: uuid.UUID | None
    rate_plan_id: uuid.UUID | None
    start: date
    end: date  # exclusive (the morning after the last night)
    nights: int
    unit_price: Decimal
    amount: Decimal


def accommodation_runs(rr: ReservationRoom) -> list[AccommodationRun]:
    runs: list[AccommodationRun] = []
    nights = sorted(rr.nights, key=lambda n: n.night)
    i = 0
    while i < len(nights):
        j = i
        while (
            j + 1 < len(nights)
            and nights[j + 1].price == nights[i].price
            and nights[j + 1].night == nights[j].night + timedelta(days=1)
        ):
            j += 1
        count = j - i + 1
        runs.append(
            AccommodationRun(
                reservation_room_id=rr.id,
                room_type_id=rr.room_type_id,
                room_id=rr.room_id,
                rate_plan_id=rr.rate_plan_id,
                start=nights[i].night,
                end=nights[j].night + timedelta(days=1),
                nights=count,
                unit_price=nights[i].price,
                amount=nights[i].price * count,
            )
        )
        i = j + 1
    return runs


@dataclass(frozen=True)
class Totals:
    accommodation: Decimal
    charges: Decimal
    taxes: list[dict[str, Any]]
    tax_total: Decimal
    grand_total: Decimal
    paid_total: Decimal
    transferred: Decimal  # to company accounts (part of paid_total)

    @property
    def subtotal(self) -> Decimal:
        return self.accommodation + self.charges

    @property
    def balance(self) -> Decimal:
        return self.grand_total - self.paid_total


def _paid(payments: list[Payment]) -> tuple[Decimal, Decimal]:
    live = [p for p in payments if not p.is_void]
    transferred = sum((p.amount_base for p in live if p.method == "city_ledger"), ZERO)
    return sum((signed_base(p) for p in live), ZERO), transferred


def folio_totals(
    res: Reservation, charges: list[FolioCharge], payments: list[Payment], part: str | None
) -> Totals:
    """Totals of the whole folio (`part` None) or of one part of a split folio.
    The guest's part is summed from its charges; the company's part is the
    rest, so the two always add up to the reservation's stored totals."""
    if part is None:
        paid, transferred = _paid(payments)
        return Totals(
            res.accommodation_total,
            res.charges_total,
            list(res.tax_breakdown),
            res.tax_total,
            res.grand_total,
            paid,
            transferred,
        )
    guest_charges = [c for c in charges if not c.is_void and charge_folio(c) == "guest"]
    guest_taxes = merge_tax_lines(*(c.tax_breakdown for c in guest_charges))
    guest_amount = sum((c.amount for c in guest_charges), ZERO)
    guest_tax = sum((Decimal(t["amount"]) for t in guest_taxes if not t["is_inclusive"]), ZERO)
    paid, transferred = _paid([p for p in payments if p.folio == part])
    if part == "guest":
        return Totals(ZERO, guest_amount, guest_taxes, guest_tax, guest_amount + guest_tax, paid, transferred)
    return Totals(
        res.accommodation_total,
        res.charges_total - guest_amount,
        subtract_tax_lines(res.tax_breakdown, guest_taxes),
        res.tax_total - guest_tax,
        res.grand_total - guest_amount - guest_tax,
        paid,
        transferred,
    )


@dataclass
class Statement:
    """What a folio screen or document shows: the whole folio, or one part of
    a split folio (`part`)."""

    reservation: Reservation
    accommodation: list[AccommodationRun]
    charges: list[FolioCharge]  # including voided ones (shown struck through)
    payments: list[Payment]  # including voided ones
    invoices: list[Invoice]
    totals: Totals
    part: str | None = None

    @property
    def balance(self) -> Decimal:
        return self.totals.balance


async def statement(db: AsyncSession, res: Reservation, part: str | None = None) -> Statement:
    """`part` ('guest' / 'company') is ignored unless the folio is split."""
    part = part if is_split(res) else None
    live = [rr for rr in res.rooms if rr.occupies_inventory]
    invoices = list(
        await db.scalars(select(Invoice).where(Invoice.reservation_id == res.id).order_by(Invoice.created_at))
    )
    charges = await charges_of(db, res.id, include_void=True)
    payments = await payments_of(db, res.id, include_void=True)
    totals = folio_totals(res, charges, payments, part)
    if part is not None:
        charges = [c for c in charges if charge_folio(c) == part]
        payments = [p for p in payments if p.folio == part]
        invoices = [i for i in invoices if i.folio == part]
    return Statement(
        reservation=res,
        accommodation=[run for rr in live for run in accommodation_runs(rr)] if part != "guest" else [],
        charges=charges,
        payments=payments,
        invoices=invoices,
        totals=totals,
        part=part,
    )
