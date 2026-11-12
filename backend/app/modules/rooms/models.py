from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    ForeignKeyConstraint,
    Numeric,
    SmallInteger,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.models import Base, Timestamps, UUIDPk, Versioned

HOUSEKEEPING_STATUSES = ("clean", "dirty", "in_progress", "inspected")
BED_TYPES = ("single", "double", "queen", "king", "twin", "sofa_bed", "bunk", "crib")
BATHROOM_TYPES = ("private_shower", "private_bathtub", "private_shower_bathtub", "shared")
AMENITY_SCOPES = ("room", "hotel")


class Amenity(UUIDPk, Timestamps, Versioned, Base):
    __tablename__ = "amenities"

    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[dict[str, str]] = mapped_column(JSONB)
    icon: Mapped[str | None] = mapped_column(String(40))
    scope: Mapped[str] = mapped_column(String(10), server_default="room")
    sort_order: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))

    __table_args__ = (
        UniqueConstraint("hotel_id", "code"),
        UniqueConstraint("hotel_id", "id"),
        CheckConstraint("scope IN ('room','hotel')", name="scope"),
    )


room_type_amenities = Table(
    "room_type_amenities",
    Base.metadata,
    Column(
        "room_type_id", UUID(as_uuid=True), ForeignKey("room_types.id", ondelete="CASCADE"), primary_key=True
    ),
    Column(
        "amenity_id", UUID(as_uuid=True), ForeignKey("amenities.id", ondelete="CASCADE"), primary_key=True
    ),
)

room_amenities = Table(
    "room_amenities",
    Base.metadata,
    Column("room_id", UUID(as_uuid=True), ForeignKey("rooms.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "amenity_id", UUID(as_uuid=True), ForeignKey("amenities.id", ondelete="CASCADE"), primary_key=True
    ),
)


class RoomType(UUIDPk, Timestamps, Versioned, Base):
    """A sellable room category (shown as "Room category" in the UI)."""

    __tablename__ = "room_types"

    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[dict[str, str]] = mapped_column(JSONB)
    description: Mapped[dict[str, str]] = mapped_column(JSONB, server_default=text("'{}'"))
    base_occupancy: Mapped[int] = mapped_column(SmallInteger)
    max_occupancy: Mapped[int] = mapped_column(SmallInteger)
    max_adults: Mapped[int] = mapped_column(SmallInteger)
    max_children: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    bed_configuration: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default=text("'[]'"))
    size_sqm: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    base_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    extra_adult_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default="0")
    extra_child_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default="0")
    color: Mapped[str | None] = mapped_column(String(9))
    sort_order: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))

    amenities: Mapped[list[Amenity]] = relationship(
        secondary=room_type_amenities, lazy="selectin", order_by=Amenity.sort_order
    )

    __table_args__ = (
        UniqueConstraint("hotel_id", "code"),
        UniqueConstraint("hotel_id", "id"),
        CheckConstraint("base_occupancy >= 1", name="base_occupancy_min"),
        CheckConstraint("max_occupancy >= base_occupancy", name="max_ge_base"),
        CheckConstraint("max_adults >= 1 AND max_adults <= max_occupancy", name="max_adults"),
        CheckConstraint("max_children >= 0 AND max_children <= max_occupancy", name="max_children"),
        CheckConstraint(
            "base_price >= 0 AND extra_adult_price >= 0 AND extra_child_price >= 0",
            name="prices_positive",
        ),
    )


class Room(UUIDPk, Timestamps, Versioned, Base):
    __tablename__ = "rooms"

    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"))
    room_type_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    building_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    floor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    number: Mapped[str] = mapped_column(String(20))
    name: Mapped[str | None] = mapped_column(String(100))
    max_occupancy: Mapped[int | None] = mapped_column(SmallInteger)
    bed_configuration: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    size_sqm: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    bathroom: Mapped[str | None] = mapped_column(String(40))
    has_balcony: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    view: Mapped[str | None] = mapped_column(String(60))
    base_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    housekeeping_status: Mapped[str] = mapped_column(String(20), server_default="clean")
    notes: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))

    amenities: Mapped[list[Amenity]] = relationship(
        secondary=room_amenities, lazy="selectin", order_by=Amenity.sort_order
    )

    __table_args__ = (
        # Composite FKs: a room can only reference a type/building/floor of its own hotel.
        ForeignKeyConstraint(
            ["hotel_id", "room_type_id"],
            ["room_types.hotel_id", "room_types.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["hotel_id", "building_id"],
            ["buildings.hotel_id", "buildings.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(["hotel_id", "floor_id"], ["floors.hotel_id", "floors.id"], ondelete="RESTRICT"),
        UniqueConstraint("hotel_id", "number"),
        UniqueConstraint("hotel_id", "id"),
        CheckConstraint(
            "housekeeping_status IN ('clean','dirty','in_progress','inspected')",
            name="housekeeping_status",
        ),
        CheckConstraint("max_occupancy IS NULL OR max_occupancy >= 1", name="max_occupancy_min"),
        CheckConstraint("base_price IS NULL OR base_price >= 0", name="base_price_positive"),
    )
