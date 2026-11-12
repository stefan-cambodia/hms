from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, Timestamps, UUIDPk, Versioned

FACILITY_PRICING_MODES = ("free", "paid", "on_request")
SERVICE_PRICING_UNITS = ("per_item", "per_night", "per_person", "per_person_night", "per_stay")


class Facility(UUIDPk, Timestamps, Versioned, Base):
    """A hotel facility: pool, restaurant, spa, parking..."""

    __tablename__ = "facilities"

    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(40))
    category: Mapped[str] = mapped_column(String(40), server_default="other")
    name: Mapped[dict[str, str]] = mapped_column(JSONB)
    description: Mapped[dict[str, str]] = mapped_column(JSONB, server_default=text("'{}'"))
    # {"mon": [["07:00","22:00"]], ..., "sun": []}; missing day = closed
    opening_hours: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    is_available: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    pricing_mode: Mapped[str] = mapped_column(String(20), server_default="free")
    price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    price_unit: Mapped[str | None] = mapped_column(String(30))
    conditions: Mapped[dict[str, str]] = mapped_column(JSONB, server_default=text("'{}'"))
    notes: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))

    __table_args__ = (
        UniqueConstraint("hotel_id", "code"),
        UniqueConstraint("hotel_id", "id"),
        CheckConstraint("pricing_mode IN ('free','paid','on_request')", name="pricing_mode"),
        CheckConstraint("price IS NULL OR price >= 0", name="price_positive"),
    )


class Service(UUIDPk, Timestamps, Versioned, Base):
    """A sellable extra that can be added to a reservation (breakfast, transfer...)."""

    __tablename__ = "services"

    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[dict[str, str]] = mapped_column(JSONB)
    description: Mapped[dict[str, str]] = mapped_column(JSONB, server_default=text("'{}'"))
    facility_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    pricing_unit: Mapped[str] = mapped_column(String(30), server_default="per_item")
    sort_order: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))

    __table_args__ = (
        ForeignKeyConstraint(
            ["hotel_id", "facility_id"],
            ["facilities.hotel_id", "facilities.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("hotel_id", "code"),
        UniqueConstraint("hotel_id", "id"),
        CheckConstraint(
            "pricing_unit IN ('per_item','per_night','per_person','per_person_night','per_stay')",
            name="pricing_unit",
        ),
        CheckConstraint("price >= 0", name="price_positive"),
    )


class TaxRate(UUIDPk, Timestamps, Versioned, Base):
    __tablename__ = "tax_rates"

    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[dict[str, str]] = mapped_column(JSONB)
    kind: Mapped[str] = mapped_column(String(30))  # percent | fixed_per_night | fixed_per_person_night
    rate: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    is_inclusive: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    applies_to: Mapped[str] = mapped_column(String(20), server_default="all")
    sort_order: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))

    __table_args__ = (
        UniqueConstraint("hotel_id", "code"),
        CheckConstraint("kind IN ('percent','fixed_per_night','fixed_per_person_night')", name="kind"),
        CheckConstraint(
            "applies_to IN ('accommodation','services','food_beverage','all')", name="applies_to"
        ),
        CheckConstraint("rate >= 0", name="rate_positive"),
        CheckConstraint("kind <> 'percent' OR rate <= 100", name="percent_max"),
    )
