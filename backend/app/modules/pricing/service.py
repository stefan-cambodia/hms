"""Pricing engine: the ONLY place prices and taxes are calculated.

Reservations, the front desk and (later) channel pushes all call `quote()`.
Current scope: base price (room override or category), occupancy supplements,
taxes. Rate plans, daily rates and pricing rules (seasons, weekends, long
stay...) will extend `nightly_price()` without changing any caller.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.money import ZERO, round_money
from app.modules.facilities.models import TaxRate
from app.modules.rooms.models import Room, RoomType


@dataclass
class StayRequest:
    room_type: RoomType
    room: Room | None
    arrival: date
    departure: date
    adults: int
    children: int


@dataclass
class NightPrice:
    night: date
    price: Decimal
    source: str


@dataclass
class StayQuote:
    nights: list[NightPrice]
    accommodation_total: Decimal


@dataclass
class TaxLine:
    code: str
    name: dict[str, str]
    kind: str
    rate: Decimal
    is_inclusive: bool
    amount: Decimal


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


def nights_between(arrival: date, departure: date) -> list[date]:
    return [arrival + timedelta(days=i) for i in range((departure - arrival).days)]


def nightly_price(stay: StayRequest, night: date, currency: str) -> NightPrice:
    rt = stay.room_type
    base = stay.room.base_price if stay.room and stay.room.base_price is not None else rt.base_price
    source = "room_base" if stay.room and stay.room.base_price is not None else "category_base"
    # Supplements apply to guests beyond the category's standard occupancy:
    # adults first fill the standard places, then children.
    extra_adults = max(0, stay.adults - rt.base_occupancy)
    free_places = max(0, rt.base_occupancy - stay.adults)
    extra_children = max(0, stay.children - free_places)
    price = base + extra_adults * rt.extra_adult_price + extra_children * rt.extra_child_price
    return NightPrice(night=night, price=round_money(price, currency), source=source)


async def active_taxes(db: AsyncSession, hotel_id: uuid.UUID, scope: str) -> list[TaxRate]:
    rows = await db.scalars(
        select(TaxRate)
        .where(
            TaxRate.hotel_id == hotel_id,
            TaxRate.is_active.is_(True),
            TaxRate.applies_to.in_((scope, "all")),
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
        else:  # fixed_per_person_night
            amount = t.rate * person_nights
        lines.append(
            TaxLine(
                code=t.code,
                name=t.name,
                kind=t.kind,
                rate=t.rate,
                is_inclusive=t.is_inclusive,
                amount=round_money(amount, currency),
            )
        )
    return lines


async def quote(db: AsyncSession, hotel_id: uuid.UUID, currency: str, stays: list[StayRequest]) -> Quote:
    stay_quotes = []
    room_nights = person_nights = 0
    for s in stays:
        nights = [nightly_price(s, n, currency) for n in nights_between(s.arrival, s.departure)]
        stay_quotes.append(StayQuote(nights=nights, accommodation_total=sum((n.price for n in nights), ZERO)))
        room_nights += len(nights)
        person_nights += len(nights) * (s.adults + s.children)
    accommodation = sum((q.accommodation_total for q in stay_quotes), ZERO)
    taxes = compute_taxes(
        await active_taxes(db, hotel_id, "accommodation"), accommodation, room_nights, person_nights, currency
    )
    return Quote(currency=currency, stays=stay_quotes, accommodation_total=accommodation, taxes=taxes)
