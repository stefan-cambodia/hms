from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Index,
    LargeBinary,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, Timestamps, UUIDPk, Versioned


class Guest(UUIDPk, Timestamps, Versioned, Base):
    """Guest profile (CRM). Scoped to one hotel for tenant isolation."""

    __tablename__ = "guests"

    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"))
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(CITEXT)
    phone: Mapped[str | None] = mapped_column(String(40))
    phone_normalized: Mapped[str | None] = mapped_column(String(20))
    nationality: Mapped[str | None] = mapped_column(String(2))
    preferred_language: Mapped[str | None] = mapped_column(String(8))
    address: Mapped[str | None] = mapped_column(String(300))
    city: Mapped[str | None] = mapped_column(String(100))
    country_code: Mapped[str | None] = mapped_column(String(2))
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    vip_level: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(40)), server_default=text("'{}'"))
    preferences: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    notes: Mapped[str | None] = mapped_column(Text)
    # Identity documents: number encrypted at rest; reads need guests.view_sensitive.
    id_document_type: Mapped[str | None] = mapped_column(String(30))
    id_document_number: Mapped[bytes | None] = mapped_column(LargeBinary)
    id_document_country: Mapped[str | None] = mapped_column(String(2))
    id_document_expiry: Mapped[date | None] = mapped_column(Date)
    marketing_consent: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    __table_args__ = (
        UniqueConstraint("hotel_id", "id"),
        Index("ix_guests_hotel_email", "hotel_id", "email"),
        Index("ix_guests_hotel_phone", "hotel_id", "phone_normalized"),
        Index(
            "ix_guests_name_trgm",
            text("(lower(first_name || ' ' || last_name)) gin_trgm_ops"),
            postgresql_using="gin",
        ),
    )
