"""Vehicle rental: the hotel's fleet (scooters, cars, bicycles, tuk-tuks...),
rental contracts and their payments.

A vehicle can never be rented twice for overlapping periods: an exclusion
constraint on (vehicle, period) covers every reserved or ongoing rental, like
the room allocation ledger. Prices are fixed when the rental is booked; late
return, fuel and damage charges are added at return. The driving licence
number is stored encrypted.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSTZRANGE, UUID, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, Timestamps, UUIDPk, Versioned

VEHICLE_KINDS = ("scooter", "motorbike", "car", "van", "bicycle", "e_bike", "tuk_tuk", "boat", "other")
# Kinds a guest may drive only with a valid licence (unless a driver is provided).
LICENCE_KINDS = ("scooter", "motorbike", "car", "van", "boat")
VEHICLE_STATUSES = ("available", "maintenance", "retired")
RENTAL_STATUSES = ("reserved", "out", "returned", "cancelled", "no_show")
DEPOSIT_KINDS = ("none", "cash", "card_hold", "passport", "id_card", "other")


class Vehicle(UUIDPk, Timestamps, Versioned, Base):
    __tablename__ = "vehicles"

    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(20))
    plate: Mapped[str | None] = mapped_column(String(20))
    kind: Mapped[str] = mapped_column(String(20))
    make: Mapped[str | None] = mapped_column(String(60))
    model: Mapped[str | None] = mapped_column(String(60))
    color: Mapped[str | None] = mapped_column(String(30))
    year: Mapped[int | None] = mapped_column(SmallInteger)
    seats: Mapped[int] = mapped_column(SmallInteger, server_default="2")
    transmission: Mapped[str | None] = mapped_column(String(10))
    daily_rate: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    hourly_rate: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    driver_daily_rate: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    deposit_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default="0")
    odometer: Mapped[int] = mapped_column(Integer, server_default="0")
    status: Mapped[str] = mapped_column(String(15), server_default="available")
    insurance_expiry: Mapped[date | None] = mapped_column(Date)
    registration_expiry: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(SmallInteger, server_default="0")

    __table_args__ = (
        UniqueConstraint("hotel_id", "code"),
        UniqueConstraint("hotel_id", "id"),
        CheckConstraint(
            "kind IN ('scooter','motorbike','car','van','bicycle','e_bike','tuk_tuk','boat','other')",
            name="kind",
        ),
        CheckConstraint("status IN ('available','maintenance','retired')", name="status"),
        CheckConstraint(
            "transmission IS NULL OR transmission IN ('manual','automatic')", name="transmission"
        ),
        CheckConstraint(
            "daily_rate >= 0 AND (hourly_rate IS NULL OR hourly_rate >= 0) "
            "AND (driver_daily_rate IS NULL OR driver_daily_rate >= 0) AND deposit_amount >= 0",
            name="rates_positive",
        ),
        CheckConstraint("seats > 0 AND odometer >= 0", name="counts_positive"),
    )


class Rental(UUIDPk, Timestamps, Versioned, Base):
    __tablename__ = "vehicle_rentals"

    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"))
    number: Mapped[str] = mapped_column(String(20))
    vehicle_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    guest_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    reservation_room_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("reservation_rooms.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(15), server_default="reserved")
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    picked_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The period the vehicle is committed to; the exclusion constraint uses it.
    period: Mapped[Any] = mapped_column(
        TSTZRANGE, Computed("tstzrange(start_at, coalesce(returned_at, end_at), '[)')", persisted=True)
    )
    with_driver: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    licence_number: Mapped[bytes | None] = mapped_column(LargeBinary)
    licence_last4: Mapped[str | None] = mapped_column(String(4))
    licence_country: Mapped[str | None] = mapped_column(String(2))
    licence_expiry: Mapped[date | None] = mapped_column(Date)
    odometer_out: Mapped[int | None] = mapped_column(Integer)
    odometer_in: Mapped[int | None] = mapped_column(Integer)
    fuel_out: Mapped[int | None] = mapped_column(SmallInteger)
    fuel_in: Mapped[int | None] = mapped_column(SmallInteger)
    condition_out: Mapped[str | None] = mapped_column(Text)
    condition_in: Mapped[str | None] = mapped_column(Text)
    deposit_kind: Mapped[str] = mapped_column(String(15), server_default="none")
    deposit_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    deposit_currency: Mapped[str | None] = mapped_column(String(3))
    deposit_note: Mapped[str | None] = mapped_column(String(200))
    deposit_returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    base_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default="0")
    driver_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default="0")
    late_fee: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default="0")
    fuel_charge: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default="0")
    damage_charge: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default="0")
    damage_note: Mapped[str | None] = mapped_column(String(300))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default="0")
    discount_reason: Mapped[str | None] = mapped_column(String(300))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default="0")
    tax_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default="0")
    tax_breakdown: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default=text("'[]'"))
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default="0")
    paid_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default="0")
    notes: Mapped[str | None] = mapped_column(Text)
    cancel_reason: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    __table_args__ = (
        ForeignKeyConstraint(
            ["hotel_id", "vehicle_id"], ["vehicles.hotel_id", "vehicles.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(["hotel_id", "guest_id"], ["guests.hotel_id", "guests.id"], ondelete="RESTRICT"),
        UniqueConstraint("hotel_id", "number"),
        UniqueConstraint("hotel_id", "id"),
        CheckConstraint("end_at > start_at", name="dates"),
        CheckConstraint("status IN ('reserved','out','returned','cancelled','no_show')", name="status"),
        CheckConstraint(
            "deposit_kind IN ('none','cash','card_hold','passport','id_card','other')", name="deposit_kind"
        ),
        CheckConstraint(
            "(fuel_out IS NULL OR fuel_out BETWEEN 0 AND 8) AND (fuel_in IS NULL OR fuel_in BETWEEN 0 AND 8)",
            name="fuel",
        ),
        CheckConstraint(
            "odometer_in IS NULL OR odometer_out IS NULL OR odometer_in >= odometer_out", name="odometer"
        ),
        CheckConstraint(
            "late_fee >= 0 AND fuel_charge >= 0 AND damage_charge >= 0 AND discount_amount >= 0",
            name="charges",
        ),
        ExcludeConstraint(
            ("vehicle_id", "="),
            ("period", "&&"),
            name="ex_vehicle_rentals_no_overlap",
            using="gist",
            where=text("status IN ('reserved', 'out')"),
        ),
        Index("ix_vehicle_rentals_hotel_start", "hotel_id", "start_at"),
    )


class RentalPayment(UUIDPk, Timestamps, Base):
    """Payment of a rental (append-only; mistakes are voided)."""

    __tablename__ = "vehicle_rental_payments"

    hotel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    rental_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    method: Mapped[str] = mapped_column(String(20))
    amount: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    currency: Mapped[str] = mapped_column(String(3))
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(18, 6), server_default="1")
    amount_base: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    tendered: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    reference: Mapped[str | None] = mapped_column(String(100))
    card_brand: Mapped[str | None] = mapped_column(String(20))
    card_last4: Mapped[str | None] = mapped_column(String(4))
    reservation_room_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    folio_charge_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    received_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    is_void: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    void_reason: Mapped[str | None] = mapped_column(String(500))
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    voided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    __table_args__ = (
        ForeignKeyConstraint(
            ["hotel_id", "rental_id"], ["vehicle_rentals.hotel_id", "vehicle_rentals.id"], ondelete="CASCADE"
        ),
        CheckConstraint(
            "method IN ('cash','card','bank_transfer','online','other','room_charge')", name="method"
        ),
        CheckConstraint("amount > 0 AND amount_base > 0 AND exchange_rate > 0", name="amount_positive"),
        CheckConstraint("card_last4 IS NULL OR card_last4 ~ '^[0-9]{4}$'", name="card_last4"),
        CheckConstraint("(method = 'room_charge') = (folio_charge_id IS NOT NULL)", name="room_charge_link"),
        CheckConstraint("NOT is_void OR void_reason IS NOT NULL", name="void_reason"),
        Index("ix_vehicle_rental_payments_rental", "rental_id"),
    )
