from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints, model_validator

from app.core.schemas import CountryCode, CurrencyCode, InputModel, OutputModel, SafeText, UpdateModel
from app.modules.guests.schemas import GuestIn

Kind = Literal["scooter", "motorbike", "car", "van", "bicycle", "e_bike", "tuk_tuk", "boat", "other"]
Money = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2)]
Text = Annotated[SafeText, StringConstraints(max_length=2000)]
Reason = Annotated[SafeText, StringConstraints(min_length=1, max_length=300)]
Fuel = Annotated[int, Field(ge=0, le=8)]  # eighths of a tank


class VehicleIn(InputModel):
    code: Annotated[str, StringConstraints(min_length=1, max_length=20)]
    plate: Annotated[str, StringConstraints(max_length=20)] | None = None
    kind: Kind
    make: Annotated[str, StringConstraints(max_length=60)] | None = None
    model: Annotated[str, StringConstraints(max_length=60)] | None = None
    color: Annotated[str, StringConstraints(max_length=30)] | None = None
    year: int | None = Field(None, ge=1950, le=2100)
    seats: int = Field(2, ge=1, le=60)
    transmission: Literal["manual", "automatic"] | None = None
    daily_rate: Money
    hourly_rate: Money | None = None
    driver_daily_rate: Money | None = None
    deposit_amount: Money = Decimal(0)
    odometer: int = Field(0, ge=0, le=10_000_000)
    status: Literal["available", "maintenance", "retired"] = "available"
    insurance_expiry: date | None = None
    registration_expiry: date | None = None
    notes: Text | None = None
    sort_order: int = Field(0, ge=0, le=32000)


class VehicleUpdate(UpdateModel):
    code: Annotated[str, StringConstraints(min_length=1, max_length=20)] | None = None
    plate: Annotated[str, StringConstraints(max_length=20)] | None = None
    kind: Kind | None = None
    make: Annotated[str, StringConstraints(max_length=60)] | None = None
    model: Annotated[str, StringConstraints(max_length=60)] | None = None
    color: Annotated[str, StringConstraints(max_length=30)] | None = None
    year: int | None = Field(None, ge=1950, le=2100)
    seats: int | None = Field(None, ge=1, le=60)
    transmission: Literal["manual", "automatic"] | None = None
    daily_rate: Money | None = None
    hourly_rate: Money | None = None
    driver_daily_rate: Money | None = None
    deposit_amount: Money | None = None
    odometer: int | None = Field(None, ge=0, le=10_000_000)
    status: Literal["available", "maintenance", "retired"] | None = None
    insurance_expiry: date | None = None
    registration_expiry: date | None = None
    notes: Text | None = None
    sort_order: int | None = Field(None, ge=0, le=32000)


class VehicleOut(OutputModel):
    id: uuid.UUID
    code: str
    plate: str | None
    kind: str
    make: str | None
    model: str | None
    color: str | None
    year: int | None
    seats: int
    transmission: str | None
    daily_rate: Decimal
    hourly_rate: Decimal | None
    driver_daily_rate: Decimal | None
    deposit_amount: Decimal
    odometer: int
    status: str
    insurance_expiry: date | None
    registration_expiry: date | None
    notes: str | None
    sort_order: int
    version: int
    # For a requested period: free, or why not.
    available: bool | None = None
    unavailable_reason: str | None = None
    # Insurance or registration expired / expiring within 30 days.
    document_warning: str | None = None


class QuoteOut(OutputModel):
    hours: int
    charge_days: int
    base_amount: Decimal
    driver_amount: Decimal
    subtotal: Decimal
    tax_total: Decimal
    tax_breakdown: list[dict[str, Any]]
    total: Decimal
    deposit_amount: Decimal


class RentalIn(InputModel):
    vehicle_id: uuid.UUID
    start_at: datetime
    end_at: datetime
    with_driver: bool = False
    guest_id: uuid.UUID | None = None
    guest: GuestIn | None = None
    reservation_room_id: uuid.UUID | None = None
    notes: Text | None = None

    @model_validator(mode="after")
    def _shape(self) -> RentalIn:
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at")
        if (self.end_at - self.start_at).days > 90:
            raise ValueError("a rental cannot exceed 90 days")
        if not (self.guest_id or self.guest or self.reservation_room_id):
            raise ValueError("a customer is required")
        return self


class RentalUpdate(UpdateModel):
    end_at: datetime | None = None
    notes: Text | None = None


class PickupIn(UpdateModel):
    licence_number: Annotated[SafeText, StringConstraints(min_length=3, max_length=40)] | None = None
    licence_country: CountryCode | None = None
    licence_expiry: date | None = None
    odometer_out: int = Field(ge=0, le=10_000_000)
    fuel_out: Fuel | None = None
    condition_out: Text | None = None
    deposit_kind: Literal["none", "cash", "card_hold", "passport", "id_card", "other"] = "none"
    deposit_amount: Money | None = None
    deposit_currency: CurrencyCode | None = None
    deposit_note: Annotated[SafeText, StringConstraints(max_length=200)] | None = None


class ReturnIn(UpdateModel):
    returned_at: datetime | None = None
    odometer_in: int = Field(ge=0, le=10_000_000)
    fuel_in: Fuel | None = None
    condition_in: Text | None = None
    fuel_charge: Money = Decimal(0)
    damage_charge: Money = Decimal(0)
    damage_note: Annotated[SafeText, StringConstraints(max_length=300)] | None = None
    waive_late_fee: bool = False
    deposit_returned: bool = True
    vehicle_needs_maintenance: bool = False


class DiscountIn(UpdateModel):
    amount: Money
    reason: Reason | None = None


class CancelIn(UpdateModel):
    reason: Reason


class PaymentIn(InputModel):
    method: Literal["cash", "card", "bank_transfer", "online", "other", "room_charge"]
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


class VoidIn(InputModel):
    reason: Reason


class RentalPaymentOut(OutputModel):
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


class RentalOut(OutputModel):
    id: uuid.UUID
    number: str
    vehicle_id: uuid.UUID
    vehicle_code: str
    vehicle_label: str
    vehicle_kind: str
    vehicle_odometer: int
    guest_id: uuid.UUID
    guest_name: str
    guest_phone: str | None
    reservation_room_id: uuid.UUID | None
    room_number: str | None
    in_house: bool
    status: str
    start_at: datetime
    end_at: datetime
    picked_up_at: datetime | None
    returned_at: datetime | None
    overdue: bool
    with_driver: bool
    licence_required: bool
    licence_last4: str | None
    licence_country: str | None
    licence_expiry: date | None
    odometer_out: int | None
    odometer_in: int | None
    fuel_out: int | None
    fuel_in: int | None
    condition_out: str | None
    condition_in: str | None
    deposit_kind: str
    deposit_amount: Decimal | None
    deposit_currency: str | None
    deposit_note: str | None
    deposit_returned_at: datetime | None
    base_amount: Decimal
    driver_amount: Decimal
    late_fee: Decimal
    fuel_charge: Decimal
    damage_charge: Decimal
    damage_note: str | None
    discount_amount: Decimal
    discount_reason: str | None
    subtotal: Decimal
    tax_total: Decimal
    tax_breakdown: list[dict[str, Any]]
    total: Decimal
    paid_total: Decimal
    balance: Decimal
    notes: str | None
    cancel_reason: str | None
    created_at: datetime
    version: int
    payments: list[RentalPaymentOut] = []
    change_due: Decimal | None = None
