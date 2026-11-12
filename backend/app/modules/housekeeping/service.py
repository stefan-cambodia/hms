"""Housekeeping: daily cleaning tasks, assignment, progress and inspection.

Task workflow (state machine):

    pending ──start──▶ in_progress ──complete──▶ done ──inspect──▶ inspected
       │                    │                     │
       └──skip──▶ skipped ◀─┘          reject ◀───┘ (back to pending, room dirty)

Room cleaning status follows the work: start → in_progress, complete →
clean (inspection tasks → inspected), inspect → inspected, reject → dirty.
Housekeepers act on their own or unassigned tasks; supervisors
(housekeeping.assign) plan, assign, inspect and act on any task.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit, crud, events
from app.core.context import HotelContext
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed, field_error, register_constraint
from app.core.permissions import P
from app.modules.auth.models import RolePermission, User, UserHotelRole
from app.modules.hotels.models import Hotel
from app.modules.housekeeping.models import HousekeepingTask, RoomStatusChange
from app.modules.housekeeping.status import arriving_today, ensure_task, set_room_status
from app.modules.reservations.models import ReservationRoom, RoomBlock
from app.modules.rooms.models import Room

register_constraint("uq_housekeeping_tasks_room_id_task_date_task_type", "TASK_EXISTS")

TRANSITIONS: dict[str, dict[str, str]] = {
    # action -> {from_status: to_status}
    "start": {"pending": "in_progress"},
    "complete": {"pending": "done", "in_progress": "done"},
    "skip": {"pending": "skipped", "in_progress": "skipped"},
    "inspect": {"done": "inspected"},
    "reject": {"done": "pending"},
    "reopen": {"skipped": "pending"},
}
SUPERVISOR_ACTIONS = {"inspect", "reject", "reopen"}


async def _hotel(db: AsyncSession, hotel_id: uuid.UUID) -> Hotel:
    hotel = await db.get(Hotel, hotel_id)
    assert hotel is not None
    return hotel


def _require(ctx: HotelContext, permission: P) -> None:
    if not ctx.has(permission):
        raise Forbidden("PERMISSION_DENIED", params={"permission": permission})


async def staff(db: AsyncSession, hotel_id: uuid.UUID) -> list[User]:
    """Active users who can carry out housekeeping tasks in this hotel."""
    stmt = (
        select(User)
        .join(UserHotelRole, UserHotelRole.user_id == User.id)
        .join(RolePermission, RolePermission.role_id == UserHotelRole.role_id)
        .where(
            UserHotelRole.hotel_id == hotel_id,
            RolePermission.permission == P.HOUSEKEEPING_UPDATE,
            User.is_active.is_(True),
        )
        .distinct()
        .order_by(User.full_name)
    )
    return list(await db.scalars(stmt))


async def _check_assignee(db: AsyncSession, hotel_id: uuid.UUID, user_id: uuid.UUID | None) -> None:
    if user_id is None:
        return
    if user_id not in {u.id for u in await staff(db, hotel_id)}:
        raise ValidationFailed(
            "NOT_HOUSEKEEPING_STAFF", fields=[field_error("assigned_to", "NOT_HOUSEKEEPING_STAFF")]
        )


async def _emit(db: AsyncSession, ctx: HotelContext, task: HousekeepingTask, action: str) -> None:
    await events.emit(
        db,
        hotel_id=ctx.hotel_id,
        entity="housekeeping_task",
        action=action,
        entity_id=task.id,
        version=task.version,
        actor=ctx.actor,
    )


# --- read model ------------------------------------------------------------------------


async def list_tasks(
    db: AsyncSession,
    ctx: HotelContext,
    *,
    day: date | None,
    assigned_to: uuid.UUID | None = None,
    unassigned: bool = False,
    status: str | None = None,
) -> list[dict[str, Any]]:
    hotel = await _hotel(db, ctx.hotel_id)
    day = day or hotel.today()
    stmt = (
        select(HousekeepingTask, Room)
        .join(Room, Room.id == HousekeepingTask.room_id)
        .where(HousekeepingTask.hotel_id == ctx.hotel_id, HousekeepingTask.task_date == day)
    )
    if assigned_to:
        stmt = stmt.where(HousekeepingTask.assigned_to == assigned_to)
    if unassigned:
        stmt = stmt.where(HousekeepingTask.assigned_to.is_(None))
    if status:
        stmt = stmt.where(HousekeepingTask.status == status)
    rows = (await db.execute(stmt.order_by(Room.sort_order, Room.number, HousekeepingTask.task_type))).all()
    user_ids = {u for t, _ in rows for u in (t.assigned_to, t.completed_by, t.inspected_by) if u}
    names = (
        {u.id: u.full_name for u in await db.scalars(select(User).where(User.id.in_(user_ids)))}
        if user_ids
        else {}
    )
    arrivals = set(
        await db.scalars(
            select(ReservationRoom.room_id).where(
                ReservationRoom.hotel_id == ctx.hotel_id,
                ReservationRoom.arrival == day,
                ReservationRoom.checked_in_at.is_(None),
                ReservationRoom.occupies_inventory.is_(True),
                ReservationRoom.room_id.is_not(None),
            )
        )
    )
    return [
        {
            "id": t.id,
            "room_id": room.id,
            "room_number": room.number,
            "room_type_id": room.room_type_id,
            "task_date": t.task_date,
            "task_type": t.task_type,
            "priority": t.priority,
            "status": t.status,
            "source": t.source,
            "assigned_to": t.assigned_to,
            "assigned_to_name": names.get(t.assigned_to) if t.assigned_to else None,
            "reservation_room_id": t.reservation_room_id,
            "notes": t.notes,
            "skip_reason": t.skip_reason,
            "started_at": t.started_at,
            "completed_at": t.completed_at,
            "completed_by_name": names.get(t.completed_by) if t.completed_by else None,
            "inspected_at": t.inspected_at,
            "inspected_by_name": names.get(t.inspected_by) if t.inspected_by else None,
            "room_status": room.housekeeping_status,
            "arrival_today": room.id in arrivals,
            "version": t.version,
        }
        for t, room in rows
    ]


async def task_out(db: AsyncSession, ctx: HotelContext, task: HousekeepingTask) -> dict[str, Any]:
    rows = await list_tasks(db, ctx, day=task.task_date)
    return next(r for r in rows if r["id"] == task.id)


async def room_history(db: AsyncSession, ctx: HotelContext, room_id: uuid.UUID, limit: int) -> list[dict]:
    await crud.get_scoped(db, Room, ctx.hotel_id, room_id, code="ROOM_NOT_FOUND")
    rows = list(
        await db.scalars(
            select(RoomStatusChange)
            .where(RoomStatusChange.room_id == room_id)
            .order_by(RoomStatusChange.at.desc(), RoomStatusChange.id.desc())
            .limit(limit)
        )
    )
    ids = {r.user_id for r in rows if r.user_id}
    names = {u.id: u.full_name for u in await db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}
    return [
        {
            "at": r.at,
            "from_status": r.from_status,
            "to_status": r.to_status,
            "cause": r.cause,
            "task_id": r.task_id,
            "user_name": names.get(r.user_id) if r.user_id else None,
        }
        for r in rows
    ]


# --- planning --------------------------------------------------------------------------


async def prepare_day(db: AsyncSession, ctx: HotelContext) -> dict[str, int]:
    """Create today's tasks from the situation of every room (idempotent):
    in-house guests leaving today or already overdue → departure clean;
    in-house guests staying → stayover service; vacant dirty rooms → departure
    clean. Rooms out of service are skipped. Departures are urgent when the
    next guest arrives today."""
    hotel = await _hotel(db, ctx.hotel_id)
    day = hotel.today()
    rooms = list(
        await db.scalars(select(Room).where(Room.hotel_id == ctx.hotel_id, Room.is_active.is_(True)))
    )
    blocked = set(
        await db.scalars(
            select(RoomBlock.room_id).where(
                RoomBlock.hotel_id == ctx.hotel_id, RoomBlock.start_date <= day, RoomBlock.end_date > day
            )
        )
    )
    in_house = {
        rr.room_id: rr
        for rr in await db.scalars(
            select(ReservationRoom).where(
                ReservationRoom.hotel_id == ctx.hotel_id,
                ReservationRoom.checked_in_at.is_not(None),
                ReservationRoom.checked_out_at.is_(None),
                ReservationRoom.room_id.is_not(None),
            )
        )
    }
    created = existing = 0
    for room in rooms:
        if room.id in blocked:
            continue
        stay = in_house.get(room.id)
        if stay is not None and stay.departure > day:
            task_type, rr_id = "stayover", stay.id
        elif stay is not None or room.housekeeping_status == "dirty":
            task_type, rr_id = "departure", stay.id if stay else None
        else:
            continue
        priority = "high" if task_type == "departure" and await arriving_today(db, room.id, day) else "normal"
        _, new = await ensure_task(
            db, ctx, room.id, day, task_type, source="daily", priority=priority, reservation_room_id=rr_id
        )
        created += new
        existing += not new
    audit.record(
        db,
        ctx.actor,
        "housekeeping.prepare_day",
        "housekeeping_task",
        None,
        hotel_id=ctx.hotel_id,
        changes={"day": [None, day], "created": [None, created]},
    )
    await db.commit()
    return {"created": created, "existing": existing}


async def create_task(db: AsyncSession, ctx: HotelContext, data: Any) -> HousekeepingTask:
    room = await crud.get_scoped(db, Room, ctx.hotel_id, data.room_id, code="ROOM_NOT_FOUND")
    await _check_assignee(db, ctx.hotel_id, data.assigned_to)
    hotel = await _hotel(db, ctx.hotel_id)
    task = HousekeepingTask(
        id=uuid.uuid4(),
        hotel_id=ctx.hotel_id,
        room_id=room.id,
        task_date=data.task_date or hotel.today(),
        task_type=data.task_type,
        priority=data.priority,
        status="pending",
        source="manual",
        assigned_to=data.assigned_to,
        notes=data.notes,
        created_by=ctx.actor.user_id,
        version=1,
    )
    db.add(task)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise Conflict("TASK_EXISTS") from exc
    audit.record(
        db,
        ctx.actor,
        "housekeeping_task.create",
        "housekeeping_task",
        task.id,
        hotel_id=ctx.hotel_id,
        changes={"room": [None, room.number], "type": [None, task.task_type], "date": [None, task.task_date]},
    )
    await _emit(db, ctx, task, "created")
    await db.commit()
    return task


async def update_task(db: AsyncSession, ctx: HotelContext, task_id: uuid.UUID, data: Any) -> HousekeepingTask:
    task = await crud.get_scoped(db, HousekeepingTask, ctx.hotel_id, task_id, code="TASK_NOT_FOUND")
    crud.check_version(task, data.version)
    changes = data.model_dump(exclude_unset=True, exclude={"version"})
    if "assigned_to" in changes:
        await _check_assignee(db, ctx.hotel_id, changes["assigned_to"])
    before = {k: getattr(task, k) for k in changes}
    for k, v in changes.items():
        setattr(task, k, v)
    await db.flush()
    audit.record(
        db,
        ctx.actor,
        "housekeeping_task.update",
        "housekeeping_task",
        task.id,
        hotel_id=ctx.hotel_id,
        changes=audit.diff(before, {k: getattr(task, k) for k in changes}),
    )
    await _emit(db, ctx, task, "updated")
    await db.commit()
    return task


async def assign_tasks(
    db: AsyncSession, ctx: HotelContext, task_ids: list[uuid.UUID], user_id: uuid.UUID | None
) -> int:
    await _check_assignee(db, ctx.hotel_id, user_id)
    tasks = list(
        await db.scalars(
            select(HousekeepingTask).where(
                HousekeepingTask.hotel_id == ctx.hotel_id, HousekeepingTask.id.in_(set(task_ids))
            )
        )
    )
    if len(tasks) != len(set(task_ids)):
        raise NotFound("TASK_NOT_FOUND")
    for task in tasks:
        task.assigned_to = user_id
    await db.flush()
    audit.record(
        db,
        ctx.actor,
        "housekeeping_task.assign",
        "housekeeping_task",
        None,
        hotel_id=ctx.hotel_id,
        changes={"tasks": [None, len(tasks)], "assigned_to": [None, user_id]},
    )
    for task in tasks:
        await _emit(db, ctx, task, "updated")
    await db.commit()
    return len(tasks)


async def delete_task(db: AsyncSession, ctx: HotelContext, task_id: uuid.UUID) -> None:
    task = await crud.get_scoped(db, HousekeepingTask, ctx.hotel_id, task_id, code="TASK_NOT_FOUND")
    if task.status != "pending":
        raise Conflict("TASK_NOT_PENDING")
    await db.delete(task)
    audit.record(
        db, ctx.actor, "housekeeping_task.delete", "housekeeping_task", task_id, hotel_id=ctx.hotel_id
    )
    await events.emit(
        db,
        hotel_id=ctx.hotel_id,
        entity="housekeeping_task",
        action="deleted",
        entity_id=task_id,
        actor=ctx.actor,
    )
    await db.commit()


# --- progress --------------------------------------------------------------------------


async def act(
    db: AsyncSession, ctx: HotelContext, task_id: uuid.UUID, action: str, reason: str | None
) -> HousekeepingTask:
    task = await crud.get_scoped(
        db, HousekeepingTask, ctx.hotel_id, task_id, code="TASK_NOT_FOUND", for_update=True
    )
    supervisor = ctx.has(P.HOUSEKEEPING_ASSIGN)
    if action in SUPERVISOR_ACTIONS:
        _require(ctx, P.HOUSEKEEPING_ASSIGN)
    elif not supervisor and task.assigned_to not in (None, ctx.actor.user_id):
        raise Forbidden("TASK_ASSIGNED_TO_SOMEONE_ELSE")
    target = TRANSITIONS[action].get(task.status)
    if target is None:
        raise Conflict("INVALID_TASK_TRANSITION", params={"from": task.status, "action": action})
    if action in ("skip", "reject") and not reason:
        raise ValidationFailed("REASON_REQUIRED", fields=[field_error("reason", "REASON_REQUIRED")])

    room = await db.get(Room, task.room_id, with_for_update=True)
    assert room is not None
    now = datetime.now(UTC)
    old = task.status
    task.status = target
    if action == "start":
        task.started_at = now
        task.assigned_to = task.assigned_to or ctx.actor.user_id
        if task.task_type != "inspection":
            await set_room_status(db, ctx, room, "in_progress", "task", task.id)
    elif action == "complete":
        task.started_at = task.started_at or now
        task.completed_at = now
        task.completed_by = ctx.actor.user_id
        task.assigned_to = task.assigned_to or ctx.actor.user_id
        status = "inspected" if task.task_type == "inspection" else "clean"
        await set_room_status(db, ctx, room, status, "task", task.id)
        if task.task_type == "inspection":
            task.status = "inspected"
            task.inspected_at, task.inspected_by = now, ctx.actor.user_id
    elif action == "skip":
        task.skip_reason = reason
        if room.housekeeping_status == "in_progress":
            await set_room_status(db, ctx, room, "dirty", "task", task.id)
    elif action == "inspect":
        task.inspected_at, task.inspected_by = now, ctx.actor.user_id
        await set_room_status(db, ctx, room, "inspected", "inspection", task.id)
    elif action == "reject":
        task.started_at = task.completed_at = task.completed_by = None
        task.notes = f"{task.notes}\n{reason}" if task.notes else reason
        await set_room_status(db, ctx, room, "dirty", "inspection", task.id)
    elif action == "reopen":
        task.skip_reason = None
    await db.flush()
    audit.record(
        db,
        ctx.actor,
        f"housekeeping_task.{action}",
        "housekeeping_task",
        task.id,
        hotel_id=ctx.hotel_id,
        changes={"status": [old, task.status], "room": [None, room.number], "reason": [None, reason]},
    )
    await _emit(db, ctx, task, "updated")
    await db.commit()
    return task


async def set_status_manual(db: AsyncSession, ctx: HotelContext, room_id: uuid.UUID, status: str) -> Room:
    room = await crud.get_scoped(db, Room, ctx.hotel_id, room_id, code="ROOM_NOT_FOUND")
    await set_room_status(db, ctx, room, status, "manual")
    await db.commit()
    return room
