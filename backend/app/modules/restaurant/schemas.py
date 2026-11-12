from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints, model_validator

from app.core.schemas import (
    Code,
    CurrencyCode,
    InputModel,
    LocalizedText,
    OutputModel,
    RequiredLocalizedName,
    SafeText,
    UpdateModel,
)

OutletKind = Literal["restaurant", "bar", "cafe", "room_service", "other"]
Station = Literal["kitchen", "bar", "none"]
OrderType = Literal["dine_in", "takeaway", "room_service"]
Money = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2)]
Reason = Annotated[SafeText, StringConstraints(min_length=1, max_length=300)]
ShortNote = Annotated[SafeText, StringConstraints(max_length=300)]

# --- configuration ------------------------------------------------------------------


class OutletIn(InputModel):
    code: Code
    name: RequiredLocalizedName
    kind: OutletKind = "restaurant"
    facility_id: uuid.UUID | None = None
    service_charge_percent: Annotated[Decimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)] = Decimal(
        0
    )
    sort_order: int = Field(0, ge=0, le=32000)
    is_active: bool = True


class OutletUpdate(UpdateModel):
    code: Code | None = None
    name: RequiredLocalizedName | None = None
    kind: OutletKind | None = None
    facility_id: uuid.UUID | None = None
    service_charge_percent: Annotated[Decimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)] | None = (
        None
    )
    sort_order: int | None = Field(None, ge=0, le=32000)
    is_active: bool | None = None


class OutletOut(OutputModel):
    id: uuid.UUID
    code: str
    name: dict[str, str]
    kind: str
    facility_id: uuid.UUID | None
    service_charge_percent: Decimal
    sort_order: int
    is_active: bool
    version: int


class CategoryIn(InputModel):
    outlet_id: uuid.UUID
    name: RequiredLocalizedName
    sort_order: int = Field(0, ge=0, le=32000)
    is_active: bool = True


class CategoryUpdate(UpdateModel):
    name: RequiredLocalizedName | None = None
    sort_order: int | None = Field(None, ge=0, le=32000)
    is_active: bool | None = None


class CategoryOut(OutputModel):
    id: uuid.UUID
    outlet_id: uuid.UUID
    name: dict[str, str]
    sort_order: int
    is_active: bool
    version: int


class ItemIn(InputModel):
    category_id: uuid.UUID
    code: Code | None = None
    name: RequiredLocalizedName
    description: LocalizedText = Field(default_factory=dict)
    price: Money
    station: Station = "kitchen"
    is_available: bool = True
    sort_order: int = Field(0, ge=0, le=32000)
    is_active: bool = True


class ItemUpdate(UpdateModel):
    category_id: uuid.UUID | None = None
    code: Code | None = None
    name: RequiredLocalizedName | None = None
    description: LocalizedText | None = None
    price: Money | None = None
    station: Station | None = None
    is_available: bool | None = None
    sort_order: int | None = Field(None, ge=0, le=32000)
    is_active: bool | None = None


class ItemOut(OutputModel):
    id: uuid.UUID
    outlet_id: uuid.UUID
    category_id: uuid.UUID
    code: str | None
    name: dict[str, str]
    description: dict[str, str]
    price: Decimal
    station: str
    is_available: bool
    sort_order: int
    is_active: bool
    version: int


class AvailabilityIn(InputModel):
    is_available: bool


class TableIn(InputModel):
    outlet_id: uuid.UUID
    label: Annotated[str, StringConstraints(min_length=1, max_length=20)]
    area: Annotated[str, StringConstraints(max_length=60)] | None = None
    seats: int = Field(4, ge=1, le=100)
    sort_order: int = Field(0, ge=0, le=32000)
    is_active: bool = True


class TableUpdate(UpdateModel):
    label: Annotated[str, StringConstraints(min_length=1, max_length=20)] | None = None
    area: Annotated[str, StringConstraints(max_length=60)] | None = None
    seats: int | None = Field(None, ge=1, le=100)
    sort_order: int | None = Field(None, ge=0, le=32000)
    is_active: bool | None = None


class TableOut(OutputModel):
    id: uuid.UUID
    outlet_id: uuid.UUID
    label: str
    area: str | None
    seats: int
    sort_order: int
    is_active: bool
    version: int


# --- orders --------------------------------------------------------------------------


class OrderIn(InputModel):
    outlet_id: uuid.UUID
    table_id: uuid.UUID | None = None
    order_type: OrderType = "dine_in"
    covers: int = Field(1, ge=1, le=200)
    reservation_room_id: uuid.UUID | None = None
    notes: ShortNote | None = None

    @model_validator(mode="after")
    def _shape(self) -> OrderIn:
        if self.order_type == "dine_in" and not self.table_id:
            raise ValueError("a dine-in order needs a table")
        if self.order_type == "room_service" and not self.reservation_room_id:
            raise ValueError("room service needs the guest's room")
        return self


class OrderUpdate(UpdateModel):
    table_id: uuid.UUID | None = None
    covers: int | None = Field(None, ge=1, le=200)
    reservation_room_id: uuid.UUID | None = None
    notes: ShortNote | None = None


class LineIn(InputModel):
    menu_item_id: uuid.UUID
    quantity: int = Field(1, ge=1, le=99)
    notes: ShortNote | None = None


class LinesIn(InputModel):
    items: list[LineIn] = Field(min_length=1, max_length=100)


class LineUpdate(InputModel):
    quantity: int | None = Field(None, ge=1, le=99)
    notes: ShortNote | None = None


class LineStatusIn(InputModel):
    status: Literal["preparing", "ready", "served"]


class VoidIn(InputModel):
    reason: Reason


class DiscountIn(InputModel):
    kind: Literal["percent", "amount"] | None
    value: Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2)] | None = None
    reason: Reason | None = None

    @model_validator(mode="after")
    def _shape(self) -> DiscountIn:
        if self.kind is not None and (self.value is None or not self.reason):
            raise ValueError("a discount needs a value and a reason")
        if self.kind == "percent" and self.value is not None and self.value > 100:
            raise ValueError("a percentage cannot exceed 100")
        return self


class PaymentIn(InputModel):
    method: Literal["cash", "card", "bank_transfer", "online", "other", "room_charge"]
    # Amount handed over in `currency` (for cash it may exceed the balance:
    # the difference is change).
    amount: Annotated[Decimal, Field(gt=0, max_digits=16, decimal_places=2)] | None = None
    currency: CurrencyCode | None = None
    exchange_rate: Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=6)] | None = None
    reference: Annotated[SafeText, StringConstraints(max_length=100)] | None = None
    card_brand: Literal["visa", "mastercard", "amex", "unionpay", "jcb", "discover", "other"] | None = None
    card_last4: Annotated[str, StringConstraints(pattern=r"^[0-9]{4}$")] | None = None
    reservation_room_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _shape(self) -> PaymentIn:
        if self.method != "room_charge" and self.amount is None:
            raise ValueError("amount is required")
        if self.method != "card" and (self.card_brand or self.card_last4):
            raise ValueError("card details are only for card payments")
        return self


class CancelIn(InputModel):
    reason: Reason


class LineOut(OutputModel):
    id: uuid.UUID
    menu_item_id: uuid.UUID | None
    name: dict[str, str]
    station: str
    unit_price: Decimal
    quantity: int
    amount: Decimal
    notes: str | None
    status: str
    created_at: datetime
    sent_at: datetime | None
    ready_at: datetime | None
    served_at: datetime | None
    void_reason: str | None


class OrderPaymentOut(OutputModel):
    id: uuid.UUID
    method: str
    amount: Decimal
    currency: str
    exchange_rate: Decimal
    amount_base: Decimal
    tendered: Decimal | None
    reference: str | None
    card_brand: str | None
    card_last4: str | None
    room_number: str | None = None
    received_at: datetime
    received_by_name: str | None = None
    is_void: bool
    void_reason: str | None


class GuestRef(OutputModel):
    reservation_room_id: uuid.UUID
    reservation_id: uuid.UUID
    reservation_code: str
    room_number: str | None
    guest_name: str
    in_house: bool


class OrderSummary(OutputModel):
    id: uuid.UUID
    outlet_id: uuid.UUID
    number: str
    business_date: date
    table_id: uuid.UUID | None
    table_label: str | None
    order_type: str
    covers: int
    status: str
    total: Decimal
    paid_total: Decimal
    balance: Decimal
    lines_new: int
    lines_waiting: int
    lines_ready: int
    opened_at: datetime
    opened_by_name: str | None
    guest: GuestRef | None
    version: int


class OrderOut(OrderSummary):
    discount_kind: str | None
    discount_value: Decimal | None
    discount_reason: str | None
    subtotal: Decimal
    discount_total: Decimal
    service_charge: Decimal
    service_charge_percent: Decimal
    tax_total: Decimal
    tax_breakdown: list[dict[str, Any]]
    notes: str | None
    closed_at: datetime | None
    cancel_reason: str | None
    lines: list[LineOut]
    payments: list[OrderPaymentOut]
    change_due: Decimal | None = None


class FloorTable(OutputModel):
    id: uuid.UUID
    label: str
    area: str | None
    seats: int
    order: OrderSummary | None


class KitchenTicket(OutputModel):
    order_id: uuid.UUID
    number: str
    table_label: str | None
    order_type: str
    covers: int
    room_number: str | None
    lines: list[LineOut]


class BreakfastRow(OutputModel):
    reservation_room_id: uuid.UUID
    reservation_code: str
    room_number: str | None
    guest_name: str
    adults: int
    children: int
    meal_plan: str
    served_covers: int | None


class BreakfastMarkIn(InputModel):
    reservation_room_id: uuid.UUID
    day: date | None = None
    covers: int = Field(ge=1, le=50)


class SalesReport(OutputModel):
    start: date
    end: date
    orders: int
    covers: int
    subtotal: Decimal
    discounts: Decimal
    service_charge: Decimal
    taxes: Decimal
    total: Decimal
    average_check: Decimal
    voided_lines: int
    voided_amount: Decimal
    by_category: list[dict[str, Any]]
    top_items: list[dict[str, Any]]
    by_method: list[dict[str, Any]]
