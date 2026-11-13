"""Closed days are frozen: nothing is posted into them or removed from them.

After the end-of-day closure of a date, charges dated that day can no longer
be posted or voided, and payments received that day can no longer be voided:
the closed day's figures stay what was reported. Corrections are made on the
current day (an adjustment on the folio, a refund).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict
from app.modules.nightaudit.models import DayClosure


async def last_closed(db: AsyncSession, hotel_id: uuid.UUID) -> date | None:
    return await db.scalar(select(func.max(DayClosure.business_date)).where(DayClosure.hotel_id == hotel_id))


async def ensure_open(db: AsyncSession, hotel_id: uuid.UUID, day: date) -> None:
    closed = await last_closed(db, hotel_id)
    if closed is not None and day <= closed:
        raise Conflict(
            "DAY_CLOSED",
            "This day is closed; make the correction on the current day",
            params={"date": day.isoformat(), "closed_until": closed.isoformat()},
        )


async def ensure_received_on_open_day(
    db: AsyncSession, hotel_id: uuid.UUID, received_at: datetime, tz: str
) -> None:
    await ensure_open(db, hotel_id, received_at.astimezone(ZoneInfo(tz)).date())


async def open_service_date(db: AsyncSession, hotel_id: uuid.UUID, wanted: date, today: date) -> date:
    """The date a charge is posted on: `wanted`, or today when `wanted` is
    closed (e.g. a restaurant check opened before the closure, charged to the
    room afterwards)."""
    closed = await last_closed(db, hotel_id)
    return today if closed is not None and wanted <= closed else wanted
