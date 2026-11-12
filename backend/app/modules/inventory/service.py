"""Inventory engine: availability per room category and night.

Two layers of protection against double booking:

1. Physical rooms: the `room_allocations` exclusion constraint (database).
2. Category level (bookings not yet assigned to a room): every write that
   changes supply or demand of a category takes a transaction-scoped advisory
   lock on (hotel, category), in a fixed order to avoid deadlocks, and then
   verifies that no night became negative before committing.

    available(T, n) = active rooms of T not allocated on n
                    - unassigned occupying bookings of T covering n
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict


async def lock_room_types(db: AsyncSession, hotel_id: uuid.UUID, room_type_ids: Iterable[uuid.UUID]) -> None:
    """Serialise inventory changes per category for the rest of the transaction."""
    for rt in sorted(set(room_type_ids), key=str):
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
            {"k": f"inventory:{hotel_id}:{rt}"},
        )


@dataclass(frozen=True)
class NightAvailability:
    room_type_id: uuid.UUID
    night: date
    total: int
    allocated: int
    unassigned: int

    @property
    def available(self) -> int:
        return self.total - self.allocated - self.unassigned


_AVAILABILITY_SQL = text(
    """
    WITH nights AS (
        SELECT d::date AS night FROM generate_series(CAST(:start AS date), CAST(:end AS date) - 1,
                                                    interval '1 day') AS d
    ),
    types AS (
        SELECT id FROM room_types
        WHERE hotel_id = :hotel AND (CAST(:types AS uuid[]) IS NULL OR id = ANY(CAST(:types AS uuid[])))
    ),
    totals AS (
        SELECT room_type_id, count(*) AS n FROM rooms
        WHERE hotel_id = :hotel AND is_active GROUP BY room_type_id
    ),
    allocated AS (
        SELECT r.room_type_id, nt.night, count(DISTINCT a.room_id) AS n
        FROM room_allocations a
        JOIN rooms r ON r.id = a.room_id AND r.is_active
        JOIN nights nt ON a.period @> nt.night
        WHERE a.hotel_id = :hotel
        GROUP BY r.room_type_id, nt.night
    ),
    unassigned AS (
        SELECT rr.room_type_id, nt.night, count(*) AS n
        FROM reservation_rooms rr
        JOIN nights nt ON rr.stay @> nt.night
        WHERE rr.hotel_id = :hotel AND rr.room_id IS NULL AND rr.occupies_inventory
        GROUP BY rr.room_type_id, nt.night
    )
    SELECT t.id, nt.night, coalesce(tt.n, 0), coalesce(al.n, 0), coalesce(un.n, 0)
    FROM types t
    CROSS JOIN nights nt
    LEFT JOIN totals tt ON tt.room_type_id = t.id
    LEFT JOIN allocated al ON al.room_type_id = t.id AND al.night = nt.night
    LEFT JOIN unassigned un ON un.room_type_id = t.id AND un.night = nt.night
    ORDER BY t.id, nt.night
    """
)


async def availability(
    db: AsyncSession,
    hotel_id: uuid.UUID,
    start: date,
    end: date,
    room_type_ids: Iterable[uuid.UUID] | None = None,
) -> list[NightAvailability]:
    types = [str(t) for t in room_type_ids] if room_type_ids is not None else None
    rows = await db.execute(
        _AVAILABILITY_SQL, {"hotel": hotel_id, "start": start, "end": end, "types": types}
    )
    return [NightAvailability(rt, night, total, alloc, un) for rt, night, total, alloc, un in rows]


async def ensure_not_oversold(
    db: AsyncSession,
    hotel_id: uuid.UUID,
    room_type_ids: Iterable[uuid.UUID],
    start: date,
    end: date,
) -> list[NightAvailability]:
    """Call after flushing a change, while holding the category locks.
    Raises NO_AVAILABILITY listing the first sold-out night."""
    await db.flush()
    rows = await availability(db, hotel_id, start, end, room_type_ids)
    short = [r for r in rows if r.available < 0]
    if short:
        first = short[0]
        raise Conflict(
            "NO_AVAILABILITY",
            "Not enough rooms available in this category",
            params={"night": first.night.isoformat(), "room_type_id": str(first.room_type_id)},
        )
    return rows


async def oversold_nights(
    db: AsyncSession, hotel_id: uuid.UUID, room_type_ids: Iterable[uuid.UUID], start: date, end: date
) -> list[NightAvailability]:
    await db.flush()
    return [r for r in await availability(db, hotel_id, start, end, room_type_ids) if r.available < 0]
