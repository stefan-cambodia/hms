from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import EmailStr, Field, StringConstraints

from app.core.schemas import (
    Code,
    CountryCode,
    CurrencyCode,
    InputModel,
    LanguageCode,
    Money,
    NonEmptyShortStr,
    Notes,
    OutputModel,
    SafeText,
    UpdateModel,
)

Method = Literal["cash", "card", "bank_transfer", "online", "other"]
Str100 = Annotated[str, StringConstraints(max_length=100)]
Str300 = Annotated[str, StringConstraints(max_length=300)]
Terms = Annotated[int, Field(ge=0, le=365)]


class AccountIn(InputModel):
    code: Code
    name: NonEmptyShortStr
    legal_name: Annotated[str, StringConstraints(max_length=200)] | None = None
    tax_id: Annotated[str, StringConstraints(max_length=50)] | None = None
    address: Str300 | None = None
    city: Str100 | None = None
    country_code: CountryCode | None = None
    email: EmailStr | None = None
    phone: Annotated[str, StringConstraints(max_length=50)] | None = None
    contact_name: Annotated[str, StringConstraints(max_length=200)] | None = None
    language: LanguageCode | None = None
    payment_terms_days: Terms = 30
    credit_limit: Money | None = None
    is_active: bool = True
    notes: Notes | None = None


class AccountUpdate(UpdateModel):
    name: NonEmptyShortStr | None = None
    legal_name: Annotated[str, StringConstraints(max_length=200)] | None = None
    tax_id: Annotated[str, StringConstraints(max_length=50)] | None = None
    address: Str300 | None = None
    city: Str100 | None = None
    country_code: CountryCode | None = None
    email: EmailStr | None = None
    phone: Annotated[str, StringConstraints(max_length=50)] | None = None
    contact_name: Annotated[str, StringConstraints(max_length=200)] | None = None
    language: LanguageCode | None = None
    payment_terms_days: Terms | None = None
    credit_limit: Money | None = None
    is_active: bool | None = None
    notes: Notes | None = None


class Aging(OutputModel):
    """Open amounts by days past due (not yet due counts as current)."""

    current: Decimal
    days_1_30: Decimal
    days_31_60: Decimal
    days_61_90: Decimal
    days_over_90: Decimal


class AccountOut(OutputModel):
    id: uuid.UUID
    code: str
    name: str
    legal_name: str | None
    tax_id: str | None
    address: str | None
    city: str | None
    country_code: str | None
    email: str | None
    phone: str | None
    contact_name: str | None
    language: str | None
    payment_terms_days: int
    credit_limit: Decimal | None
    is_active: bool
    notes: str | None
    version: int
    currency: str
    balance: Decimal  # owed by the company (negative: credit on the account)
    overdue: Decimal
    open_items: int


class OpenItemOut(OutputModel):
    transfer_id: uuid.UUID
    number: str  # of the transfer
    invoice_id: uuid.UUID
    invoice_number: str
    reservation_id: uuid.UUID
    reservation_code: str
    guest_name: str
    date: date
    due_date: date
    amount: Decimal
    paid: Decimal
    open: Decimal
    days_overdue: int  # 0 when not due yet
    is_void: bool


class AllocationOut(OutputModel):
    transfer_id: uuid.UUID
    invoice_number: str
    amount: Decimal


class AccountPaymentOut(OutputModel):
    id: uuid.UUID
    number: str
    method: str
    amount: Decimal
    currency: str
    exchange_rate: Decimal
    amount_base: Decimal
    reference: str | None
    notes: str | None
    received_at: datetime
    received_by_name: str | None
    is_void: bool
    void_reason: str | None
    allocations: list[AllocationOut]
    unallocated: Decimal


class AccountDetailOut(AccountOut):
    aging: Aging
    items: list[OpenItemOut]  # every transfer, newest first (open ones and settled ones)
    payments: list[AccountPaymentOut]


class AllocationIn(InputModel):
    transfer_id: uuid.UUID
    amount: Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=2)]


class AccountPaymentIn(InputModel):
    method: Method
    amount: Annotated[Decimal, Field(gt=0, max_digits=16, decimal_places=2)]
    currency: CurrencyCode | None = None
    exchange_rate: Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=6)] | None = None
    reference: Annotated[SafeText, StringConstraints(max_length=100)] | None = None
    notes: Annotated[SafeText, StringConstraints(max_length=500)] | None = None
    # Which invoices it pays; when left out, the oldest open ones first.
    allocations: list[AllocationIn] | None = Field(None, max_length=200)


class VoidIn(InputModel):
    reason: Annotated[SafeText, StringConstraints(min_length=1, max_length=500)]


class TransferIn(InputModel):
    language: LanguageCode | None = None  # of the invoice (default: the company's)
