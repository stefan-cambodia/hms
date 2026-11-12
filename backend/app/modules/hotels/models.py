from __future__ import annotations

import uuid
from datetime import time
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
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, Timestamps, UUIDPk, Versioned


class Organization(UUIDPk, Timestamps, Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200))


class Hotel(UUIDPk, Timestamps, Versioned, Base):
    __tablename__ = "hotels"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True
    )
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200))
    legal_name: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[dict[str, str]] = mapped_column(JSONB, server_default=text("'{}'"))
    address_line1: Mapped[str | None] = mapped_column(String(200))
    address_line2: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(100))
    region: Mapped[str | None] = mapped_column(String(100))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    country_code: Mapped[str | None] = mapped_column(String(2))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    phone: Mapped[str | None] = mapped_column(String(40))
    email: Mapped[str | None] = mapped_column(String(200))
    website: Mapped[str | None] = mapped_column(String(300))
    social_links: Mapped[dict[str, str]] = mapped_column(JSONB, server_default=text("'{}'"))
    timezone: Mapped[str] = mapped_column(String(64), server_default="UTC")
    default_language: Mapped[str] = mapped_column(String(8), server_default="en")
    supported_languages: Mapped[list[str]] = mapped_column(
        ARRAY(String(8)), server_default=text("ARRAY['en','fr','zh-CN','ru','km']::varchar[]")
    )
    currency_code: Mapped[str] = mapped_column(String(3), server_default="USD")
    check_in_time: Mapped[time] = mapped_column(Time, server_default=text("'14:00'"))
    check_out_time: Mapped[time] = mapped_column(Time, server_default=text("'12:00'"))
    tax_id: Mapped[str | None] = mapped_column(String(60))
    billing_info: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    # {"cancellation": LocalizedText, "payment": LocalizedText, "house_rules": LocalizedText}
    policies: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))

    __table_args__ = (
        UniqueConstraint("organization_id", "code"),
        CheckConstraint("latitude IS NULL OR latitude BETWEEN -90 AND 90", name="latitude_range"),
        CheckConstraint("longitude IS NULL OR longitude BETWEEN -180 AND 180", name="longitude_range"),
    )


class Building(UUIDPk, Timestamps, Versioned, Base):
    __tablename__ = "buildings"

    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200))
    sort_order: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))

    __table_args__ = (
        UniqueConstraint("hotel_id", "code"),
        UniqueConstraint("hotel_id", "id"),  # target for composite tenant FKs
    )


class Floor(UUIDPk, Timestamps, Versioned, Base):
    __tablename__ = "floors"

    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"))
    building_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    level: Mapped[int] = mapped_column(SmallInteger)
    name: Mapped[str] = mapped_column(String(100))
    sort_order: Mapped[int] = mapped_column(SmallInteger, server_default="0")

    __table_args__ = (
        ForeignKeyConstraint(
            ["hotel_id", "building_id"], ["buildings.hotel_id", "buildings.id"], ondelete="RESTRICT"
        ),
        UniqueConstraint("building_id", "level"),
        UniqueConstraint("hotel_id", "id"),
    )
