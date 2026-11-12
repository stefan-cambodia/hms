"""Reservations and the room allocation ledger (the integrity core).

`room_allocations` is the single source of truth for physical room occupancy.
It is maintained exclusively by database triggers on `reservation_rooms` and
`room_blocks`, and carries an exclusion constraint so that no code path can
ever give one room two overlapping occupancies.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import DATERANGE, JSONB, UUID, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.models import Base, Timestamps, UUIDPk, Versioned

RESERVATION_STATUSES = ("pending", "confirmed", "checked_in", "checked_out", "cancelled", "no_show")
OCCUPYING_STATUSES = ("pending", "confirmed", "checked_in", "checked_out")
SOURCES = ("direct", "website", "booking_com", "agoda", "walk_in", "phone", "email", "other")
BLOCK_REASONS = ("maintenance", "out_of_service", "owner_use", "other")


class DocumentSequence(Base):
    """Per-hotel counters for human-readable numbers (reservations, invoices...)."""

    __tablename__ = "document_sequences"

    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))
    next_value: Mapped[int] = mapped_column(BigInteger, server_default="1")

    __table_args__ = (PrimaryKeyConstraint("hotel_id", "kind"),)


class Reservation(UUIDPk, Timestamps, Versioned, Base):
    __tablename__ = "reservations"

    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(30))
    booker_guest_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(20))
    external_ref: Mapped[str | None] = mapped_column(String(100))
    arrival: Mapped[date] = mapped_column(Date)
    departure: Mapped[date] = mapped_column(Date)
    adults: Mapped[int] = mapped_column(SmallInteger)
    children: Mapped[int] = mapped_column(SmallInteger)
    currency: Mapped[str] = mapped_column(String(3))
    accommodation_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default="0")
    tax_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default="0")
    grand_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default="0")
    paid_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default="0")
    tax_breakdown: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default=text("'[]'"))
    is_overbooked: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    special_requests: Mapped[str | None] = mapped_column(Text)
    internal_notes: Mapped[str | None] = mapped_column(Text)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_reason: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    rooms: Mapped[list[ReservationRoom]] = relationship(
        back_populates="reservation",
        lazy="selectin",
        order_by="ReservationRoom.arrival",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["hotel_id", "booker_guest_id"], ["guests.hotel_id", "guests.id"], ondelete="RESTRICT"
        ),
        UniqueConstraint("hotel_id", "code"),
        UniqueConstraint("hotel_id", "id"),
        CheckConstraint("departure > arrival", name="dates"),
        CheckConstraint(
            "status IN ('pending','confirmed','checked_in','checked_out','cancelled','no_show')",
            name="status",
        ),
        CheckConstraint(
            "source IN ('direct','website','booking_com','agoda','walk_in','phone','email','other')",
            name="source",
        ),
        CheckConstraint("adults >= 1 AND children >= 0", name="occupancy"),
        Index("ix_reservations_hotel_dates", "hotel_id", "arrival", "departure"),
        Index("ix_reservations_hotel_status", "hotel_id", "status"),
    )


class ReservationRoom(UUIDPk, Base):
    """One room (or one room-category booking awaiting assignment) within a reservation."""

    __tablename__ = "reservation_rooms"

    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"))
    reservation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reservations.id", ondelete="CASCADE"), index=True
    )
    room_type_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    room_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    rate_plan_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    arrival: Mapped[date] = mapped_column(Date)
    departure: Mapped[date] = mapped_column(Date)
    stay: Mapped[Any] = mapped_column(
        DATERANGE, Computed("daterange(arrival, departure, '[)')", persisted=True)
    )
    adults: Mapped[int] = mapped_column(SmallInteger)
    children: Mapped[int] = mapped_column(SmallInteger)
    occupies_inventory: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    accommodation_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default="0")
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checked_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    reservation: Mapped[Reservation] = relationship(back_populates="rooms", lazy="raise")
    nights: Mapped[list[ReservationNight]] = relationship(
        lazy="selectin", order_by="ReservationNight.night", cascade="all, delete-orphan"
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["hotel_id", "room_type_id"],
            ["room_types.hotel_id", "room_types.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(["hotel_id", "room_id"], ["rooms.hotel_id", "rooms.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(
            ["hotel_id", "rate_plan_id"], ["rate_plans.hotel_id", "rate_plans.id"], ondelete="RESTRICT"
        ),
        CheckConstraint("departure > arrival", name="dates"),
        CheckConstraint("adults >= 1 AND children >= 0", name="occupancy"),
        Index("ix_reservation_rooms_type_stay", "room_type_id", "stay", postgresql_using="gist"),
        Index("ix_reservation_rooms_room", "room_id"),
    )


class ReservationNight(Base):
    """Nightly price, fixed at booking time (later rate changes don't reprice it)."""

    __tablename__ = "reservation_nights"

    reservation_room_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reservation_rooms.id", ondelete="CASCADE")
    )
    night: Mapped[date] = mapped_column(Date)
    hotel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    price_source: Mapped[str] = mapped_column(String(30))
    rate_plan_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    __table_args__ = (PrimaryKeyConstraint("reservation_room_id", "night"),)


class RoomBlock(UUIDPk, Timestamps, Base):
    """A room taken out of sale for a period (maintenance, owner use...)."""

    __tablename__ = "room_blocks"

    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"))
    room_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(String(20))
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    __table_args__ = (
        ForeignKeyConstraint(["hotel_id", "room_id"], ["rooms.hotel_id", "rooms.id"], ondelete="RESTRICT"),
        CheckConstraint("end_date > start_date", name="dates"),
        CheckConstraint("reason IN ('maintenance','out_of_service','owner_use','other')", name="reason"),
    )


class RoomAllocation(Base):
    """Ledger of physical room occupancy. Written only by triggers."""

    __tablename__ = "room_allocations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    hotel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    room_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    period: Mapped[Any] = mapped_column(DATERANGE)
    reservation_room_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("reservation_rooms.id", ondelete="CASCADE"), unique=True
    )
    room_block_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("room_blocks.id", ondelete="CASCADE"), unique=True
    )

    __table_args__ = (
        ForeignKeyConstraint(["hotel_id", "room_id"], ["rooms.hotel_id", "rooms.id"], ondelete="RESTRICT"),
        CheckConstraint("num_nonnulls(reservation_room_id, room_block_id) = 1", name="one_owner"),
        CheckConstraint("NOT isempty(period)", name="non_empty"),
        ExcludeConstraint(
            ("room_id", "="),
            ("period", "&&"),
            name="ex_room_allocations_no_overlap",
            using="gist",
            deferrable=True,
            initially="IMMEDIATE",
        ),
        Index("ix_room_allocations_hotel_period", "hotel_id", "period", postgresql_using="gist"),
    )


class ReservationEvent(Base):
    """Complete modification history of a reservation (shown to staff)."""

    __tablename__ = "reservation_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    hotel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    reservation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reservations.id", ondelete="CASCADE"), index=True
    )
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    source: Mapped[str] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(40))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))


class IdempotencyKey(Base):
    """Makes creation requests safe to retry after a network failure."""

    __tablename__ = "idempotency_keys"

    hotel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    key: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    attempts: Mapped[int] = mapped_column(Integer, server_default="1")

    __table_args__ = (PrimaryKeyConstraint("hotel_id", "user_id", "key"),)
