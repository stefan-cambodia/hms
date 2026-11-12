"""Room cleaning status and automatic cleaning tasks.

Every change of `rooms.housekeeping_status` goes through `set_room_status`
(manual change, check-out, room move, task progress, end of maintenance), so
the history, the audit log and the real-time update can never be skipped.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit, events
from app.core.context import HotelContext
from app.modules.housekeeping.models import HousekeepingTask, RoomStatusChange
from app.modules.reservations.models import Reservation, ReservationRoom
from app.modules.rooms.models import Room

PRIORITY_RANK = {"low": 0, "normal": 1, "high": 2, "urgent": 3}


async def set_room_status(
    db: AsyncSession,
    ctx: HotelContext,
    room: Room,
    status: str,
    cause: str,
    task_id: uuid.UUID | None = None,
) -> bool:
    if room.housekeeping_status == status:
        return False
    old = room.housekeeping_status
    room.housekeeping_status = status
    db.add(
        RoomStatusChange(
            hotel_id=ctx.hotel_id,
            room_id=room.id,
            from_status=old,
            to_status=status,
            cause=cause,
            task_id=task_id,
            user_id=ctx.actor.user_id,
        )
    )
    await db.flush()
    audit.record(
        db,
        ctx.actor,
        "room.housekeeping_status",
        "room",
        room.id,
        hotel_id=ctx.hotel_id,
        changes={"housekeeping_status": [old, status], "cause": [None, cause]},
    )
    await events.emit(
        db,
        hotel_id=ctx.hotel_id,
        entity="room",
        action="updated",
        entity_id=room.id,
        version=room.version,
        actor=ctx.actor,
    )
    return True


async def arriving_today(db: AsyncSession, room_id: uuid.UUID, day: date) -> bool:
    """A guest is expected in this room today and has not checked in yet."""
    found = await db.scalar(
        select(ReservationRoom.id)
        .join(Reservation, Reservation.id == ReservationRoom.reservation_id)
        .where(
            ReservationRoom.room_id == room_id,
            ReservationRoom.arrival == day,
            ReservationRoom.checked_in_at.is_(None),
            ReservationRoom.occupies_inventory.is_(True),
            Reservation.status.in_(("pending", "confirmed")),
        )
        .limit(1)
    )
    return found is not None


async def ensure_task(
    db: AsyncSession,
    ctx: HotelContext,
    room_id: uuid.UUID,
    day: date,
    task_type: str,
    *,
    source: str,
    priority: str = "normal",
    reservation_room_id: uuid.UUID | None = None,
) -> tuple[HousekeepingTask, bool]:
    """Get or create the task of this type for the room and day. A finished
    task is reopened when the room needs the same work again the same day.
    Returns (task, created)."""
    task = (
        await db.scalars(
            select(HousekeepingTask).where(
                HousekeepingTask.room_id == room_id,
                HousekeepingTask.task_date == day,
                HousekeepingTask.task_type == task_type,
            )
        )
    ).one_or_none()
    if task is None:
        task = HousekeepingTask(
            id=uuid.uuid4(),
            hotel_id=ctx.hotel_id,
            room_id=room_id,
            task_date=day,
            task_type=task_type,
            priority=priority,
            status="pending",
            source=source,
            reservation_room_id=reservation_room_id,
            created_by=ctx.actor.user_id,
            version=1,
        )
        db.add(task)
        await db.flush()
        await events.emit(
            db,
            hotel_id=ctx.hotel_id,
            entity="housekeeping_task",
            action="created",
            entity_id=task.id,
            actor=ctx.actor,
        )
        return task, True
    changed = False
    if task.status in ("done", "inspected", "skipped") and source != "daily":
        task.status = "pending"
        task.started_at = task.completed_at = task.inspected_at = None
        task.completed_by = task.inspected_by = None
        task.skip_reason = None
        changed = True
    if PRIORITY_RANK[priority] > PRIORITY_RANK[task.priority]:
        task.priority = priority
        changed = True
    if changed:
        await db.flush()
        await events.emit(
            db,
            hotel_id=ctx.hotel_id,
            entity="housekeeping_task",
            action="updated",
            entity_id=task.id,
            actor=ctx.actor,
        )
    return task, False


async def after_departure(
    db: AsyncSession, ctx: HotelContext, room: Room, day: date, cause: str, rr_id: uuid.UUID | None
) -> None:
    """The guest left the room: it is dirty and needs a departure clean, urgent
    when the next guest arrives today. A pending stayover service is dropped."""
    await set_room_status(db, ctx, room, "dirty", cause)
    priority = "high" if await arriving_today(db, room.id, day) else "normal"
    await ensure_task(
        db, ctx, room.id, day, "departure", source=cause, priority=priority, reservation_room_id=rr_id
    )
    for task in await db.scalars(
        select(HousekeepingTask).where(
            HousekeepingTask.room_id == room.id,
            HousekeepingTask.task_date == day,
            HousekeepingTask.task_type == "stayover",
            HousekeepingTask.status == "pending",
        )
    ):
        task.status = "skipped"
        task.skip_reason = "guest_departed"
        await db.flush()
        await events.emit(
            db,
            hotel_id=ctx.hotel_id,
            entity="housekeeping_task",
            action="updated",
            entity_id=task.id,
            actor=ctx.actor,
        )
