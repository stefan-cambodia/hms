"""Restaurant & bar (point of sale): outlets, menus, tables, orders, payments.

An outlet is a place that sells food or drinks (restaurant, bar, café, room
service). Orders (checks) hold lines whose names and prices are copied from
the menu when ordered, so later menu changes never alter an order. Payments
are append-only like folio payments; a "room charge" posts the check to the
guest's folio (with its tax lines) instead of taking money.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, Timestamps, UUIDPk, Versioned

OUTLET_KINDS = ("restaurant", "bar", "cafe", "room_service", "other")
STATIONS = ("kitchen", "bar", "none")
ORDER_TYPES = ("dine_in", "takeaway", "room_service")
ORDER_STATUSES = ("open", "closed", "cancelled")
LINE_STATUSES = ("new", "sent", "preparing", "ready", "served", "void")
PAY_METHODS = ("cash", "card", "bank_transfer", "online", "other", "room_charge")


class Outlet(UUIDPk, Timestamps, Versioned, Base):
    __tablename__ = "restaurant_outlets"

    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[dict[str, str]] = mapped_column(JSONB)
    kind: Mapped[str] = mapped_column(String(20), server_default="restaurant")
    facility_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    service_charge_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), server_default="0")
    sort_order: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))

    __table_args__ = (
        ForeignKeyConstraint(
            ["hotel_id", "facility_id"], ["facilities.hotel_id", "facilities.id"], ondelete="SET NULL"
        ),
        UniqueConstraint("hotel_id", "code"),
        UniqueConstraint("hotel_id", "id"),
        CheckConstraint("kind IN ('restaurant','bar','cafe','room_service','other')", name="kind"),
        CheckConstraint(
            "service_charge_percent >= 0 AND service_charge_percent <= 100", name="service_charge"
        ),
    )


class MenuCategory(UUIDPk, Timestamps, Versioned, Base):
    __tablename__ = "menu_categories"

    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"))
    outlet_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    name: Mapped[dict[str, str]] = mapped_column(JSONB)
    sort_order: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))

    __table_args__ = (
        ForeignKeyConstraint(
            ["hotel_id", "outlet_id"],
            ["restaurant_outlets.hotel_id", "restaurant_outlets.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("hotel_id", "id"),
    )


class MenuItem(UUIDPk, Timestamps, Versioned, Base):
    __tablename__ = "menu_items"

    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"))
    outlet_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    category_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    code: Mapped[str | None] = mapped_column(String(40))
    name: Mapped[dict[str, str]] = mapped_column(JSONB)
    description: Mapped[dict[str, str]] = mapped_column(JSONB, server_default=text("'{}'"))
    price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    station: Mapped[str] = mapped_column(String(10), server_default="kitchen")
    # False while sold out ("86"): the item stays on the menu but cannot be ordered.
    is_available: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))

    __table_args__ = (
        ForeignKeyConstraint(
            ["hotel_id", "outlet_id"],
            ["restaurant_outlets.hotel_id", "restaurant_outlets.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["hotel_id", "category_id"],
            ["menu_categories.hotel_id", "menu_categories.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("hotel_id", "id"),
        CheckConstraint("price >= 0", name="price_positive"),
        CheckConstraint("station IN ('kitchen','bar','none')", name="station"),
        Index("ix_menu_items_outlet", "outlet_id"),
    )


class DiningTable(UUIDPk, Timestamps, Versioned, Base):
    __tablename__ = "restaurant_tables"

    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"))
    outlet_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    label: Mapped[str] = mapped_column(String(20))
    area: Mapped[str | None] = mapped_column(String(60))
    seats: Mapped[int] = mapped_column(SmallInteger, server_default="4")
    sort_order: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))

    __table_args__ = (
        ForeignKeyConstraint(
            ["hotel_id", "outlet_id"],
            ["restaurant_outlets.hotel_id", "restaurant_outlets.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("outlet_id", "label"),
        UniqueConstraint("hotel_id", "id"),
        CheckConstraint("seats > 0", name="seats_positive"),
    )


class Order(UUIDPk, Timestamps, Versioned, Base):
    """A check: what a table (or a takeaway / room-service customer) orders."""

    __tablename__ = "restaurant_orders"

    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"))
    outlet_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    number: Mapped[str] = mapped_column(String(20))
    business_date: Mapped[date] = mapped_column(Date)
    table_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    order_type: Mapped[str] = mapped_column(String(20), server_default="dine_in")
    covers: Mapped[int] = mapped_column(SmallInteger, server_default="1")
    status: Mapped[str] = mapped_column(String(10), server_default="open")
    # Guest staying at the hotel (room service, or identified at the table).
    reservation_room_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("reservation_rooms.id", ondelete="SET NULL")
    )
    discount_kind: Mapped[str | None] = mapped_column(String(10))
    discount_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    discount_reason: Mapped[str | None] = mapped_column(String(300))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default="0")
    discount_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default="0")
    service_charge: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default="0")
    tax_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default="0")
    tax_breakdown: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default=text("'[]'"))
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default="0")
    paid_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default="0")
    notes: Mapped[str | None] = mapped_column(Text)
    opened_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(500))

    __table_args__ = (
        ForeignKeyConstraint(
            ["hotel_id", "outlet_id"],
            ["restaurant_outlets.hotel_id", "restaurant_outlets.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["hotel_id", "table_id"],
            ["restaurant_tables.hotel_id", "restaurant_tables.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("hotel_id", "number"),
        UniqueConstraint("hotel_id", "id"),
        CheckConstraint("order_type IN ('dine_in','takeaway','room_service')", name="order_type"),
        CheckConstraint("status IN ('open','closed','cancelled')", name="status"),
        CheckConstraint("covers > 0", name="covers_positive"),
        CheckConstraint(
            "discount_kind IS NULL OR discount_kind IN ('percent','amount')", name="discount_kind"
        ),
        # A table has at most one open check.
        Index(
            "uq_restaurant_orders_open_table",
            "table_id",
            unique=True,
            postgresql_where=text("status = 'open' AND table_id IS NOT NULL"),
        ),
        Index("ix_restaurant_orders_outlet_date", "outlet_id", "business_date"),
    )


class OrderLine(UUIDPk, Base):
    __tablename__ = "restaurant_order_lines"

    hotel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("restaurant_orders.id", ondelete="CASCADE"), index=True
    )
    menu_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("menu_items.id", ondelete="SET NULL"))
    category_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    name: Mapped[dict[str, str]] = mapped_column(JSONB)
    station: Mapped[str] = mapped_column(String(10))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    quantity: Mapped[int] = mapped_column(SmallInteger)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    notes: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(10), server_default="new")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    served_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    void_reason: Mapped[str | None] = mapped_column(String(300))
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    voided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price >= 0", name="price_positive"),
        CheckConstraint("status IN ('new','sent','preparing','ready','served','void')", name="status"),
        CheckConstraint("station IN ('kitchen','bar','none')", name="station"),
        CheckConstraint("status <> 'void' OR void_reason IS NOT NULL", name="void_reason"),
    )


class OrderPayment(UUIDPk, Timestamps, Base):
    """Settlement of a check (append-only; mistakes are voided)."""

    __tablename__ = "restaurant_payments"

    hotel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
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
            ["hotel_id", "order_id"],
            ["restaurant_orders.hotel_id", "restaurant_orders.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "method IN ('cash','card','bank_transfer','online','other','room_charge')", name="method"
        ),
        CheckConstraint("amount > 0 AND amount_base > 0 AND exchange_rate > 0", name="amount_positive"),
        CheckConstraint("card_last4 IS NULL OR card_last4 ~ '^[0-9]{4}$'", name="card_last4"),
        CheckConstraint("(method = 'room_charge') = (folio_charge_id IS NOT NULL)", name="room_charge_link"),
        CheckConstraint("NOT is_void OR void_reason IS NOT NULL", name="void_reason"),
        Index("ix_restaurant_payments_order", "order_id"),
        Index("ix_restaurant_payments_hotel_received", "hotel_id", "received_at"),
    )


class BreakfastMark(Base):
    """A staying guest's included breakfast was served (one mark per stay and day)."""

    __tablename__ = "breakfast_marks"

    hotel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    reservation_room_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reservation_rooms.id", ondelete="CASCADE")
    )
    day: Mapped[date] = mapped_column(Date)
    covers: Mapped[int] = mapped_column(SmallInteger)
    marked_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    marked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        PrimaryKeyConstraint("reservation_room_id", "day"),
        CheckConstraint("covers > 0", name="covers_positive"),
        Index("ix_breakfast_marks_hotel_day", "hotel_id", "day"),
    )
