"""Cleaning tasks and the history of every room cleaning-status change.

The room's current cleaning state lives on `rooms.housekeeping_status`
(clean / dirty / in_progress / inspected). Occupancy, out-of-service and
maintenance are derived from their own sources (allocation ledger, room
blocks, open maintenance requests) and never stored here.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, Timestamps, UUIDPk, Versioned

TASK_TYPES = ("departure", "stayover", "deep_clean", "touch_up", "inspection")
TASK_STATUSES = ("pending", "in_progress", "done", "inspected", "skipped")
PRIORITIES = ("low", "normal", "high", "urgent")
TASK_SOURCES = ("manual", "daily", "check_out", "room_move", "maintenance")


class HousekeepingTask(UUIDPk, Timestamps, Versioned, Base):
    __tablename__ = "housekeeping_tasks"

    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"))
    room_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    task_date: Mapped[date] = mapped_column(Date)
    task_type: Mapped[str] = mapped_column(String(20))
    priority: Mapped[str] = mapped_column(String(10), server_default="normal")
    status: Mapped[str] = mapped_column(String(20), server_default="pending")
    source: Mapped[str] = mapped_column(String(20), server_default="manual")
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reservation_room_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("reservation_rooms.id", ondelete="SET NULL")
    )
    notes: Mapped[str | None] = mapped_column(Text)
    skip_reason: Mapped[str | None] = mapped_column(String(500))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    inspected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    inspected_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    __table_args__ = (
        ForeignKeyConstraint(["hotel_id", "room_id"], ["rooms.hotel_id", "rooms.id"], ondelete="CASCADE"),
        # One task of each type per room and day: daily preparation is idempotent.
        UniqueConstraint("room_id", "task_date", "task_type"),
        CheckConstraint(
            "task_type IN ('departure','stayover','deep_clean','touch_up','inspection')", name="task_type"
        ),
        CheckConstraint("status IN ('pending','in_progress','done','inspected','skipped')", name="status"),
        CheckConstraint("priority IN ('low','normal','high','urgent')", name="priority"),
        CheckConstraint("source IN ('manual','daily','check_out','room_move','maintenance')", name="source"),
        CheckConstraint("status <> 'skipped' OR skip_reason IS NOT NULL", name="skip_reason"),
        Index("ix_housekeeping_tasks_hotel_date", "hotel_id", "task_date"),
    )


class RoomStatusChange(Base):
    """Append-only log of cleaning-status changes (who, when, why)."""

    __tablename__ = "room_status_changes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    hotel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    room_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rooms.id", ondelete="CASCADE"))
    from_status: Mapped[str] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20))
    cause: Mapped[str] = mapped_column(String(20))
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("housekeeping_tasks.id", ondelete="SET NULL")
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_room_status_changes_room_at", "room_id", "at"),)
