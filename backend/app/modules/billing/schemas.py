from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints, model_validator

from app.core.schemas import (
    CountryCode,
    CurrencyCode,
    InputModel,
    LanguageCode,
    OutputModel,
    SafeText,
    UpdateModel,
)

ExchangeRate = Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=6)]
SignedAmount = Annotated[Decimal, Field(max_digits=14, decimal_places=2, ge=-(10**11), le=10**11)]
Reason = Annotated[SafeText, StringConstraints(min_length=1, max_length=500)]

# --- currencies -------------------------------------------------------------------


class CurrencyIn(InputModel):
    code: CurrencyCode
    units_per_base: ExchangeRate
    is_active: bool = True


class CurrencyUpdate(UpdateModel):
    units_per_base: ExchangeRate | None = None
    is_active: bool | None = None


class CurrencyOut(OutputModel):
    id: uuid.UUID
    code: str
    units_per_base: Decimal
    is_active: bool
    version: int
    updated_at: datetime


# --- charges ----------------------------------------------------------------------

FeeType = Literal["cancellation", "no_show", "early_departure", "late_checkout", "damage", "other"]


class ChargeIn(InputModel):
    """A service from the catalog (service_id), a free-text item, a fee or an
    adjustment (a signed correction, e.g. a goodwill discount)."""

    kind: Literal["service", "fee", "adjustment"] = "service"
    service_id: uuid.UUID | None = None
    fee_type: FeeType | None = None
    description: Annotated[SafeText, StringConstraints(max_length=300)] | None = None
    quantity: Annotated[Decimal, Field(gt=0, le=10_000, max_digits=10, decimal_places=2)] = Decimal(1)
    unit_price: SignedAmount | None = None
    service_date: date | None = None
    reservation_room_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _shape(self) -> ChargeIn:
        if self.kind == "service":
            if self.fee_type:
                raise ValueError("fee_type is only for fees")
            if self.service_id is None and not (self.description and self.unit_price is not None):
                raise ValueError("a free-text item needs a description and a unit price")
        elif self.kind == "fee":
            if not self.fee_type or self.unit_price is None or self.service_id:
                raise ValueError("a fee needs a fee_type and a unit price")
        else:
            if self.service_id or self.fee_type or not self.description or not self.unit_price:
                raise ValueError("an adjustment needs a description and a non-zero amount")
        if self.kind != "adjustment" and self.unit_price is not None and self.unit_price < 0:
            raise ValueError("only adjustments can be negative")
        return self


class VoidIn(InputModel):
    reason: Reason


class ChargeOut(OutputModel):
    id: uuid.UUID
    reservation_room_id: uuid.UUID | None
    kind: str
    fee_type: str | None
    service_id: uuid.UUID | None
    name: dict[str, str]
    description: str | None
    service_date: date
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal
    tax_amount: Decimal
    tax_breakdown: list[dict[str, Any]]
    is_void: bool
    void_reason: str | None
    voided_at: datetime | None
    voided_by_name: str | None = None
    created_by_name: str | None = None
    created_at: datetime


# --- payments ---------------------------------------------------------------------


class PaymentIn(InputModel):
    kind: Literal["payment", "deposit", "refund"] = "payment"
    method: Literal["cash", "card", "bank_transfer", "online", "other"]
    amount: Annotated[Decimal, Field(gt=0, max_digits=16, decimal_places=2)]
    currency: CurrencyCode | None = None
    # The rate the client showed to the user; refused if it is no longer current.
    exchange_rate: ExchangeRate | None = None
    reference: Annotated[SafeText, StringConstraints(max_length=100)] | None = None
    card_brand: Literal["visa", "mastercard", "amex", "unionpay", "jcb", "discover", "other"] | None = None
    card_last4: Annotated[str, StringConstraints(pattern=r"^[0-9]{4}$")] | None = None
    notes: Annotated[SafeText, StringConstraints(max_length=500)] | None = None

    @model_validator(mode="after")
    def _card_fields(self) -> PaymentIn:
        if self.method != "card" and (self.card_brand or self.card_last4):
            raise ValueError("card details are only for card payments")
        return self


class PaymentOut(OutputModel):
    id: uuid.UUID
    number: str
    kind: str
    method: str
    amount: Decimal
    currency: str
    exchange_rate: Decimal
    amount_base: Decimal
    reference: str | None
    card_brand: str | None
    card_last4: str | None
    notes: str | None
    received_at: datetime
    received_by_name: str | None = None
    is_void: bool
    void_reason: str | None
    voided_at: datetime | None
    voided_by_name: str | None = None


class PaymentListItem(PaymentOut):
    reservation_id: uuid.UUID
    reservation_code: str
    guest_name: str


class PaymentSummaryRow(OutputModel):
    method: str
    currency: str
    kind: str
    count: int
    amount: Decimal
    amount_base: Decimal


class PaymentReport(OutputModel):
    items: list[PaymentListItem]
    total: int
    limit: int
    offset: int
    summary: list[PaymentSummaryRow]
    net_base: Decimal


# --- invoices ---------------------------------------------------------------------


class BillToIn(InputModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    company: Annotated[str, StringConstraints(max_length=200)] | None = None
    tax_id: Annotated[str, StringConstraints(max_length=60)] | None = None
    address: Annotated[str, StringConstraints(max_length=300)] | None = None
    city: Annotated[str, StringConstraints(max_length=100)] | None = None
    country_code: CountryCode | None = None
    email: Annotated[str, StringConstraints(max_length=320)] | None = None


class IssueInvoiceIn(InputModel):
    language: LanguageCode | None = None
    bill_to: BillToIn | None = None


class InvoiceOut(OutputModel):
    id: uuid.UUID
    reservation_id: uuid.UUID
    number: str
    status: str
    issue_date: date
    language: str
    currency: str
    bill_to: dict[str, Any]
    subtotal: Decimal
    tax_total: Decimal
    total: Decimal
    paid_total: Decimal
    balance: Decimal
    void_reason: str | None
    voided_at: datetime | None
    created_at: datetime


class InvoiceListItem(InvoiceOut):
    reservation_code: str


# --- folio ------------------------------------------------------------------------


class AccommodationRunOut(OutputModel):
    reservation_room_id: uuid.UUID
    room_type_id: uuid.UUID
    room_id: uuid.UUID | None
    rate_plan_id: uuid.UUID | None
    start: date
    end: date
    nights: int
    unit_price: Decimal
    amount: Decimal


class FolioTotals(OutputModel):
    accommodation: Decimal
    charges: Decimal
    tax_total: Decimal
    grand_total: Decimal
    paid_total: Decimal
    balance: Decimal


class FolioOut(OutputModel):
    reservation_id: uuid.UUID
    version: int
    currency: str
    accommodation: list[AccommodationRunOut]
    charges: list[ChargeOut]
    payments: list[PaymentOut]
    taxes: list[dict[str, Any]]
    totals: FolioTotals
    invoices: list[InvoiceOut]
    # True when the active invoice no longer matches the folio (charges or
    # payments changed after it was issued).
    invoice_outdated: bool
