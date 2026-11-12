"""Maintenance requests (rooms, facilities or any location) and their history.

A request can take its room out of service: it then owns a room block
(reason `maintenance`), which goes through the same allocation ledger as
stays, so a room under repair can never be sold.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, Timestamps, UUIDPk, Versioned

CATEGORIES = (
    "plumbing",
    "electrical",
    "air_conditioning",
    "furniture",
    "appliance",
    "building",
    "it_network",
    "pest_control",
    "other",
)
STATUSES = ("reported", "in_progress", "on_hold", "completed", "cancelled")
OPEN_STATUSES = ("reported", "in_progress", "on_hold")
PRIORITIES = ("low", "normal", "high", "urgent")


class MaintenanceRequest(UUIDPk, Timestamps, Versioned, Base):
    __tablename__ = "maintenance_requests"

    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"))
    number: Mapped[str] = mapped_column(String(20))
    room_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    facility_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    location: Mapped[str | None] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(20), server_default="other")
    priority: Mapped[str] = mapped_column(String(10), server_default="normal")
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), server_default="reported")
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reported_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    room_block_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("room_blocks.id", ondelete="SET NULL"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        ForeignKeyConstraint(["hotel_id", "room_id"], ["rooms.hotel_id", "rooms.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(
            ["hotel_id", "facility_id"], ["facilities.hotel_id", "facilities.id"], ondelete="RESTRICT"
        ),
        UniqueConstraint("hotel_id", "number"),
        CheckConstraint(
            "room_id IS NOT NULL OR facility_id IS NOT NULL OR location IS NOT NULL", name="where"
        ),
        CheckConstraint(
            "category IN ('plumbing','electrical','air_conditioning','furniture','appliance','building',"
            "'it_network','pest_control','other')",
            name="category",
        ),
        CheckConstraint("priority IN ('low','normal','high','urgent')", name="priority"),
        CheckConstraint(
            "status IN ('reported','in_progress','on_hold','completed','cancelled')", name="status"
        ),
        Index("ix_maintenance_requests_hotel_status", "hotel_id", "status"),
        Index("ix_maintenance_requests_room", "room_id"),
    )


class MaintenanceUpdate(Base):
    """History of a request: status changes, assignments, comments, blocks."""

    __tablename__ = "maintenance_updates"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    hotel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("maintenance_requests.id", ondelete="CASCADE"), index=True
    )
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    action: Mapped[str] = mapped_column(String(30))
    comment: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
