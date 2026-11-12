"""Maintenance requests.

Workflow: reported → in_progress ⇄ on_hold → completed (or cancelled from any
open state); a closed request can be reopened. A request on a room can take
it out of service: it then owns a room block (reason `maintenance`) created
through the reservation engine, so the allocation ledger refuses the block
if a guest occupies the room and no booking can land on it while it is
blocked. Completing or cancelling the request releases the room from tonight
(the past part of the block stays as history) and, after works, marks it
dirty with a cleaning task.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit, crud, events, sequences
from app.core.context import HotelContext
from app.core.errors import Conflict, Forbidden, ValidationFailed, field_error
from app.core.permissions import P
from app.modules.auth.models import RolePermission, User, UserHotelRole
from app.modules.facilities.models import Facility
from app.modules.hotels.models import Hotel
from app.modules.housekeeping.status import ensure_task, set_room_status
from app.modules.maintenance.models import OPEN_STATUSES, MaintenanceRequest, MaintenanceUpdate
from app.modules.reservations import service as reservations
from app.modules.reservations.models import RoomBlock
from app.modules.rooms.models import Room

TRANSITIONS: dict[str, set[str]] = {
    "reported": {"in_progress", "on_hold", "completed", "cancelled"},
    "in_progress": {"on_hold", "completed", "cancelled"},
    "on_hold": {"in_progress", "completed", "cancelled"},
    "completed": {"reported"},
    "cancelled": {"reported"},
}
FIELDS = ("category", "priority", "title", "description", "assigned_to")


async def _hotel(db: AsyncSession, hotel_id: uuid.UUID) -> Hotel:
    hotel = await db.get(Hotel, hotel_id)
    assert hotel is not None
    return hotel


def _require(ctx: HotelContext, permission: P) -> None:
    if not ctx.has(permission):
        raise Forbidden("PERMISSION_DENIED", params={"permission": permission})


async def technicians(db: AsyncSession, hotel_id: uuid.UUID) -> list[User]:
    """Active users who can handle maintenance requests in this hotel."""
    return list(
        await db.scalars(
            select(User)
            .join(UserHotelRole, UserHotelRole.user_id == User.id)
            .join(RolePermission, RolePermission.role_id == UserHotelRole.role_id)
            .where(
                UserHotelRole.hotel_id == hotel_id,
                RolePermission.permission == P.MAINTENANCE_MANAGE,
                User.is_active.is_(True),
            )
            .distinct()
            .order_by(User.full_name)
        )
    )


async def _check_assignee(db: AsyncSession, hotel_id: uuid.UUID, user_id: uuid.UUID | None) -> None:
    if user_id is not None and user_id not in {u.id for u in await technicians(db, hotel_id)}:
        raise ValidationFailed(
            "NOT_MAINTENANCE_STAFF", fields=[field_error("assigned_to", "NOT_MAINTENANCE_STAFF")]
        )


def _log(
    db: AsyncSession,
    ctx: HotelContext,
    req: MaintenanceRequest,
    action: str,
    comment: str | None = None,
    **details: Any,
) -> None:
    db.add(
        MaintenanceUpdate(
            hotel_id=ctx.hotel_id,
            request_id=req.id,
            user_id=ctx.actor.user_id,
            action=action,
            comment=comment,
            details=audit._jsonable(details),
        )
    )


async def _publish(
    db: AsyncSession, ctx: HotelContext, req: MaintenanceRequest, action: str, changes: dict
) -> None:
    audit.record(
        db,
        ctx.actor,
        f"maintenance_request.{action}",
        "maintenance_request",
        req.id,
        hotel_id=ctx.hotel_id,
        changes=changes,
    )
    await events.emit(
        db,
        hotel_id=ctx.hotel_id,
        entity="maintenance_request",
        action="created" if action == "create" else "updated",
        entity_id=req.id,
        version=req.version,
        actor=ctx.actor,
    )


async def get_request(
    db: AsyncSession, hotel_id: uuid.UUID, req_id: uuid.UUID, *, for_update: bool = False
) -> MaintenanceRequest:
    return await crud.get_scoped(
        db, MaintenanceRequest, hotel_id, req_id, code="MAINTENANCE_REQUEST_NOT_FOUND", for_update=for_update
    )


async def _block(db: AsyncSession, req: MaintenanceRequest) -> RoomBlock | None:
    return await db.get(RoomBlock, req.room_block_id) if req.room_block_id else None


# --- create & edit ----------------------------------------------------------------------


async def create_request(db: AsyncSession, ctx: HotelContext, data: Any) -> MaintenanceRequest:
    room = None
    if data.room_id:
        room = await crud.get_scoped(db, Room, ctx.hotel_id, data.room_id, code="ROOM_NOT_FOUND")
    if data.facility_id:
        await crud.get_scoped(db, Facility, ctx.hotel_id, data.facility_id, code="FACILITY_NOT_FOUND")
    if data.assigned_to or data.out_of_service:
        _require(ctx, P.MAINTENANCE_MANAGE)
    await _check_assignee(db, ctx.hotel_id, data.assigned_to)
    req = MaintenanceRequest(
        id=uuid.uuid4(),
        hotel_id=ctx.hotel_id,
        number=f"MT-{await sequences.next_value(db, ctx.hotel_id, 'maintenance'):06d}",
        room_id=data.room_id,
        facility_id=data.facility_id,
        location=data.location,
        category=data.category,
        priority=data.priority,
        title=data.title,
        description=data.description,
        status="reported",
        assigned_to=data.assigned_to,
        reported_by=ctx.actor.user_id,
        version=1,
    )
    db.add(req)
    await db.flush()
    _log(db, ctx, req, "reported", data.description, priority=req.priority, category=req.category)
    if data.out_of_service and room is not None:
        block = await reservations.add_block(
            db,
            ctx,
            room.id,
            data.out_of_service.start_date,
            data.out_of_service.end_date,
            "maintenance",
            f"{req.number}: {req.title}",
        )
        req.room_block_id = block.id
        await db.flush()
        _log(db, ctx, req, "out_of_service", start=block.start_date, end=block.end_date)
    await _publish(db, ctx, req, "create", {"number": [None, req.number], "title": [None, req.title]})
    await db.commit()
    return req


async def update_request(
    db: AsyncSession, ctx: HotelContext, req_id: uuid.UUID, data: Any
) -> MaintenanceRequest:
    req = await get_request(db, ctx.hotel_id, req_id)
    crud.check_version(req, data.version)
    changes = data.model_dump(exclude_unset=True, exclude={"version"})
    if "title" in changes and not changes["title"]:
        raise ValidationFailed(fields=[field_error("title", "REQUIRED")])
    if "assigned_to" in changes:
        await _check_assignee(db, ctx.hotel_id, changes["assigned_to"])
    before = {k: getattr(req, k) for k in changes}
    for k, v in changes.items():
        setattr(req, k, v)
    delta = audit.diff(before, {k: getattr(req, k) for k in changes})
    if not delta:
        return req
    await db.flush()
    if "assigned_to" in delta:
        names = {u.id: u.full_name for u in await technicians(db, ctx.hotel_id)}
        _log(db, ctx, req, "assigned", to=names.get(req.assigned_to) if req.assigned_to else None)
    other = sorted(k for k in delta if k != "assigned_to")
    if other:
        _log(db, ctx, req, "edited", fields=other)
    await _publish(db, ctx, req, "update", delta)
    await db.commit()
    return req


async def add_comment(
    db: AsyncSession, ctx: HotelContext, req_id: uuid.UUID, comment: str
) -> MaintenanceRequest:
    req = await get_request(db, ctx.hotel_id, req_id)
    _log(db, ctx, req, "comment", comment)
    req.updated_at = datetime.now(UTC)
    await db.flush()
    await _publish(db, ctx, req, "comment", {"comment": [None, comment[:200]]})
    await db.commit()
    return req


# --- status ---------------------------------------------------------------------------


async def change_status(
    db: AsyncSession, ctx: HotelContext, req_id: uuid.UUID, data: Any
) -> MaintenanceRequest:
    req = await get_request(db, ctx.hotel_id, req_id, for_update=True)
    crud.check_version(req, data.version)
    if data.status not in TRANSITIONS[req.status]:
        raise Conflict("INVALID_STATUS_TRANSITION", params={"from": req.status, "to": data.status})
    hotel = await _hotel(db, ctx.hotel_id)
    today = hotel.today()
    now = datetime.now(UTC)
    old = req.status
    req.status = data.status
    details: dict[str, Any] = {"from": old, "to": data.status}
    if data.status == "in_progress" and req.started_at is None:
        req.started_at = now
    if data.status in ("completed", "cancelled"):
        req.completed_at = now if data.status == "completed" else None
        if data.status == "completed":
            req.resolution = data.resolution or req.resolution
        block = await _block(db, req)
        if block is not None and (data.release_room or data.status == "cancelled"):
            await reservations.release_block(db, ctx, block, today)
            if block.start_date >= today:
                req.room_block_id = None
            details["room_released"] = True
        if data.status == "completed" and data.needs_cleaning and req.room_id:
            room = await db.get(Room, req.room_id)
            assert room is not None
            await set_room_status(db, ctx, room, "dirty", "maintenance")
            await ensure_task(db, ctx, room.id, today, "touch_up", source="maintenance")
            details["cleaning_requested"] = True
    if data.status == "reported":
        req.completed_at = None
    await db.flush()
    _log(
        db,
        ctx,
        req,
        "status",
        data.comment or (data.resolution if data.status == "completed" else None),
        **details,
    )
    await _publish(db, ctx, req, "status", {"status": [old, req.status]})
    await db.commit()
    return req


async def set_block(db: AsyncSession, ctx: HotelContext, req_id: uuid.UUID, data: Any) -> MaintenanceRequest:
    """Take the request's room out of service, or move/extend its block."""
    req = await get_request(db, ctx.hotel_id, req_id, for_update=True)
    crud.check_version(req, data.version)
    if req.room_id is None:
        raise ValidationFailed("NO_ROOM_TO_BLOCK")
    if req.status not in OPEN_STATUSES:
        raise Conflict("MAINTENANCE_CLOSED")
    today = (await _hotel(db, ctx.hotel_id)).today()
    block = await _block(db, req)
    if block is None or block.end_date <= today:
        # No block, or only a past one (kept as history): open a new one.
        block = await reservations.add_block(
            db, ctx, req.room_id, data.start_date, data.end_date, "maintenance", f"{req.number}: {req.title}"
        )
        req.room_block_id = block.id
    else:
        await reservations.change_block_dates(db, ctx, block, data.start_date, data.end_date)
    req.updated_at = datetime.now(UTC)
    await db.flush()
    _log(db, ctx, req, "out_of_service", start=block.start_date, end=block.end_date)
    await _publish(db, ctx, req, "block", {"block": [None, f"{block.start_date}..{block.end_date}"]})
    await db.commit()
    return req


async def release(db: AsyncSession, ctx: HotelContext, req_id: uuid.UUID, version: int) -> MaintenanceRequest:
    req = await get_request(db, ctx.hotel_id, req_id, for_update=True)
    crud.check_version(req, version)
    today = (await _hotel(db, ctx.hotel_id)).today()
    block = await _block(db, req)
    if block is None or block.end_date <= today:
        raise Conflict("ROOM_NOT_BLOCKED")
    await reservations.release_block(db, ctx, block, today)
    if block.start_date >= today:
        req.room_block_id = None
    req.updated_at = datetime.now(UTC)
    await db.flush()
    _log(db, ctx, req, "back_in_service")
    await _publish(db, ctx, req, "release", {"block": ["released", None]})
    await db.commit()
    return req


# --- read model -----------------------------------------------------------------------


async def _out(db: AsyncSession, reqs: list[MaintenanceRequest], today: Any) -> list[dict[str, Any]]:
    user_ids = {u for r in reqs for u in (r.assigned_to, r.reported_by) if u}
    names = (
        {u.id: u.full_name for u in await db.scalars(select(User).where(User.id.in_(user_ids)))}
        if user_ids
        else {}
    )
    room_ids = {r.room_id for r in reqs if r.room_id}
    numbers = (
        {r.id: r.number for r in await db.scalars(select(Room).where(Room.id.in_(room_ids)))}
        if room_ids
        else {}
    )
    block_ids = {r.room_block_id for r in reqs if r.room_block_id}
    blocks = (
        {b.id: b for b in await db.scalars(select(RoomBlock).where(RoomBlock.id.in_(block_ids)))}
        if block_ids
        else {}
    )
    out = []
    for r in reqs:
        b = blocks.get(r.room_block_id) if r.room_block_id else None
        active = b is not None and b.end_date > today
        out.append(
            {
                **{
                    f: getattr(r, f)
                    for f in (
                        "id",
                        "number",
                        "room_id",
                        "facility_id",
                        "location",
                        "category",
                        "priority",
                        "title",
                        "description",
                        "status",
                        "assigned_to",
                        "started_at",
                        "completed_at",
                        "resolution",
                        "created_at",
                        "updated_at",
                        "version",
                    )
                },
                "room_number": numbers.get(r.room_id) if r.room_id else None,
                "assigned_to_name": names.get(r.assigned_to) if r.assigned_to else None,
                "reported_by_name": names.get(r.reported_by) if r.reported_by else None,
                "block": {"id": b.id, "start_date": b.start_date, "end_date": b.end_date} if active else None,
            }
        )
    return out


async def request_out(db: AsyncSession, ctx: HotelContext, req: MaintenanceRequest, *, detail: bool) -> dict:
    today = (await _hotel(db, ctx.hotel_id)).today()
    out = (await _out(db, [req], today))[0]
    if detail:
        updates = list(
            await db.scalars(
                select(MaintenanceUpdate)
                .where(MaintenanceUpdate.request_id == req.id)
                .order_by(MaintenanceUpdate.at, MaintenanceUpdate.id)
            )
        )
        ids = {u.user_id for u in updates if u.user_id}
        names = (
            {u.id: u.full_name for u in await db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}
        )
        out["updates"] = [
            {
                "id": u.id,
                "at": u.at,
                "user_name": names.get(u.user_id) if u.user_id else None,
                "action": u.action,
                "comment": u.comment,
                "details": u.details,
            }
            for u in updates
        ]
    return out


async def list_requests(
    db: AsyncSession,
    ctx: HotelContext,
    *,
    state: str,
    room_id: uuid.UUID | None,
    priority: str | None,
    assigned_to: uuid.UUID | None,
    q: str | None,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    stmt = select(MaintenanceRequest).where(MaintenanceRequest.hotel_id == ctx.hotel_id)
    if state == "open":
        stmt = stmt.where(MaintenanceRequest.status.in_(OPEN_STATUSES))
    elif state == "closed":
        stmt = stmt.where(MaintenanceRequest.status.not_in(OPEN_STATUSES))
    if room_id:
        stmt = stmt.where(MaintenanceRequest.room_id == room_id)
    if priority:
        stmt = stmt.where(MaintenanceRequest.priority == priority)
    if assigned_to:
        stmt = stmt.where(MaintenanceRequest.assigned_to == assigned_to)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                MaintenanceRequest.number.ilike(like),
                MaintenanceRequest.title.ilike(like),
                MaintenanceRequest.location.ilike(like),
                MaintenanceRequest.room_id.in_(
                    select(Room.id).where(Room.hotel_id == ctx.hotel_id, Room.number.ilike(like))
                ),
            )
        )
    rank = func.array_position(["urgent", "high", "normal", "low"], MaintenanceRequest.priority)
    items, total = await crud.paginate(
        db, stmt.order_by(rank, MaintenanceRequest.created_at.desc()), limit=limit, offset=offset
    )
    today = (await _hotel(db, ctx.hotel_id)).today()
    return await _out(db, list(items), today), total


async def open_by_room(db: AsyncSession, hotel_id: uuid.UUID) -> dict[uuid.UUID, dict[str, Any]]:
    """Open requests per room: count and highest priority (for room boards)."""
    rank = {"low": 0, "normal": 1, "high": 2, "urgent": 3}
    out: dict[uuid.UUID, dict[str, Any]] = {}
    for r in await db.scalars(
        select(MaintenanceRequest).where(
            MaintenanceRequest.hotel_id == hotel_id,
            MaintenanceRequest.room_id.is_not(None),
            MaintenanceRequest.status.in_(OPEN_STATUSES),
        )
    ):
        cur = out.setdefault(r.room_id, {"open": 0, "priority": "low"})
        cur["open"] += 1
        if rank[r.priority] > rank[cur["priority"]]:
            cur["priority"] = r.priority
    return out
