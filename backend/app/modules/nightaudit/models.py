"""End-of-day closures (night audit).

A closure is the official record of one business day: its figures as they
were when the day was closed, and the items still open then. Closures are
append-only, and nothing can be posted into a closed day any more (see
`lock.py`): corrections are made on the current day.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, UUIDPk


class DayClosure(UUIDPk, Base):
    __tablename__ = "day_closures"

    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"))
    business_date: Mapped[date] = mapped_column(Date)
    closed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    report: Mapped[dict[str, Any]] = mapped_column(JSONB)
    open_items: Mapped[dict[str, Any]] = mapped_column(JSONB)
    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (UniqueConstraint("hotel_id", "business_date"),)
