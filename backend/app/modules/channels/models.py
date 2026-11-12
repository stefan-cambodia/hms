"""Channel manager: connections to distribution providers (SiteMinder
pmsXchange today), code mappings, the change queue, the last values each
channel acknowledged, a redacted message log and received bookings.

How availability and prices reach a channel:

1. Database triggers record every change that can alter availability, a price
   or a restriction (reservations, room assignments, blocks, rooms, rates,
   rate plans, pricing rules) as a *dirty range* (connection, room category,
   dates), in the same transaction as the change. No code path can forget it.
2. The worker recomputes the current values for those ranges with the
   inventory and pricing engines, compares them with what the channel last
   acknowledged (`channel_inventory_state`, `channel_rate_state`) and sends
   only the differences.
3. The state tables are updated only after the provider confirms success, so
   a failed send is retried with the then-current values.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, Timestamps, UUIDPk, Versioned

PROVIDERS = ("siteminder",)
ENVIRONMENTS = ("test", "production")
# Shown to staff; see docs/architecture/03-channel-manager.md §3.4.
STATES = ("credentials_saved", "test_ok", "live", "degraded", "paused")
BOOKING_IMPORT_STATUSES = ("pending", "imported", "failed", "ignored")


class ChannelConnection(UUIDPk, Timestamps, Versioned, Base):
    """Configuration, edited by administrators (optimistic locking)."""

    __tablename__ = "channel_connections"
    __table_args__ = (UniqueConstraint("hotel_id", "provider", "hotel_code"),)

    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(100))
    environment: Mapped[str] = mapped_column(String(20), server_default="test")
    endpoint_url: Mapped[str | None] = mapped_column(String(300))
    # Provider account identifier (SiteMinder: the PMS code / RequestorID).
    account_code: Mapped[str] = mapped_column(String(64))
    username: Mapped[str] = mapped_column(String(100))
    password: Mapped[bytes] = mapped_column(LargeBinary)  # encrypt_secret()
    hotel_code: Mapped[str] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    push_ari: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    pull_reservations: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    horizon_days: Mapped[int] = mapped_column(SmallInteger, server_default="365")
    pull_interval_seconds: Mapped[int] = mapped_column(Integer, server_default="180")
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))


class ChannelSyncStatus(Base):
    """Runtime state, written by the worker (kept apart from the configuration
    so that background updates never conflict with an administrator's edit)."""

    __tablename__ = "channel_sync_status"

    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("channel_connections.id", ondelete="CASCADE"), primary_key=True
    )
    hotel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    state: Mapped[str] = mapped_column(String(20), server_default="credentials_saved")
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean)
    last_test_message: Mapped[str | None] = mapped_column(String(500))
    last_push_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_pull_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))
    consecutive_failures: Mapped[int] = mapped_column(Integer, server_default="0")
    next_push_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_pull_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Last day included in the pushed horizon; each new day is added as it comes.
    horizon_end: Mapped[date | None] = mapped_column(Date)
    full_refresh_requested: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    # Providers forbid repeated full refreshes (SiteMinder: not several within 24 h).
    last_full_refresh_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Room and rate codes listed by the provider at the last mapping fetch.
    external_products: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default=text("'[]'"))
    products_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ChannelRoomMap(UUIDPk, Base):
    """Local room category ↔ the provider's room code (availability)."""

    __tablename__ = "channel_room_maps"
    __table_args__ = (
        UniqueConstraint("connection_id", "room_type_id"),
        UniqueConstraint("connection_id", "external_code"),
    )

    connection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("channel_connections.id", ondelete="CASCADE"))
    hotel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    room_type_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("room_types.id", ondelete="CASCADE"))
    external_code: Mapped[str] = mapped_column(String(64))


class ChannelRateMap(UUIDPk, Base):
    """(Room category, rate plan) ↔ the provider's rate code: prices and
    restrictions are sent for each mapped pair."""

    __tablename__ = "channel_rate_maps"
    __table_args__ = (
        UniqueConstraint("connection_id", "room_type_id", "rate_plan_id"),
        UniqueConstraint("connection_id", "room_type_id", "external_code"),
    )

    connection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("channel_connections.id", ondelete="CASCADE"))
    hotel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    room_type_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("room_types.id", ondelete="CASCADE"))
    rate_plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rate_plans.id", ondelete="CASCADE"))
    external_code: Mapped[str] = mapped_column(String(64))


class ChannelDirtyRange(Base):
    """A change waiting to be sent. Written by database triggers; NULL room
    type = every category, NULL dates = the whole horizon."""

    __tablename__ = "channel_dirty_ranges"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("channel_connections.id", ondelete="CASCADE"), index=True
    )
    room_type_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)  # exclusive
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChannelInventoryState(Base):
    """Rooms to sell per category and night, as last acknowledged by the channel."""

    __tablename__ = "channel_inventory_state"

    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("channel_connections.id", ondelete="CASCADE"), primary_key=True
    )
    room_type_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    night: Mapped[date] = mapped_column(Date, primary_key=True)
    available: Mapped[int] = mapped_column(Integer)
    acked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChannelRateState(Base):
    """Price and restrictions per category, rate plan and night, as last
    acknowledged by the channel."""

    __tablename__ = "channel_rate_state"

    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("channel_connections.id", ondelete="CASCADE"), primary_key=True
    )
    room_type_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    rate_plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    night: Mapped[date] = mapped_column(Date, primary_key=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    closed: Mapped[bool | None] = mapped_column(Boolean)
    closed_to_arrival: Mapped[bool | None] = mapped_column(Boolean)
    closed_to_departure: Mapped[bool | None] = mapped_column(Boolean)
    min_stay: Mapped[int | None] = mapped_column(SmallInteger)
    max_stay: Mapped[int | None] = mapped_column(SmallInteger)
    acked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChannelMessage(Base):
    """Exchange log for diagnostics. Bodies are stored only after card data
    and credentials have been removed (see redact.py), and truncated."""

    __tablename__ = "channel_messages"
    __table_args__ = (Index("ix_channel_messages_connection_at", "connection_id", "at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("channel_connections.id", ondelete="CASCADE"))
    hotel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    operation: Mapped[str] = mapped_column(String(40))
    outcome: Mapped[str] = mapped_column(String(10))  # ok | warning | error
    http_status: Mapped[int | None] = mapped_column(SmallInteger)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    summary: Mapped[str | None] = mapped_column(String(500))
    request_body: Mapped[str | None] = mapped_column(Text)
    response_body: Mapped[str | None] = mapped_column(Text)


class ChannelBooking(UUIDPk, Base):
    """A reservation message received from a channel, one row per revision.
    Idempotent: the same revision received twice is stored once."""

    __tablename__ = "channel_bookings"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", "revision"),
        Index("ix_channel_bookings_connection_external", "connection_id", "external_id"),
        Index("ix_channel_bookings_hotel_status", "hotel_id", "import_status"),
    )

    connection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("channel_connections.id", ondelete="CASCADE"))
    hotel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    external_id: Mapped[str] = mapped_column(String(100))
    revision: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(10))  # book | modify | cancel
    channel_name: Mapped[str | None] = mapped_column(String(100))
    message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Normalised booking (guest, stays, nightly prices...). Never card data.
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    card_brand: Mapped[str | None] = mapped_column(String(20))
    card_last4: Mapped[str | None] = mapped_column(String(4))
    import_status: Mapped[str] = mapped_column(String(10), server_default="pending")
    error_code: Mapped[str | None] = mapped_column(String(60))
    error_detail: Mapped[str | None] = mapped_column(String(500))
    reservation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("reservations.id", ondelete="SET NULL"), index=True
    )
    overbooked: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    attempts: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # When the provider was told the booking was received (after local commit).
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirm_reference: Mapped[str | None] = mapped_column(String(100))
