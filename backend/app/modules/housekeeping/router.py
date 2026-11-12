from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Query, status

from app.core.permissions import P
from app.core.schemas import InputModel
from app.modules.auth.deps import DB, hotel_ctx
from app.modules.housekeeping import service
from app.modules.housekeeping.schemas import (
    ActionIn,
    AssignIn,
    PrepareOut,
    StaffOut,
    StatusChangeOut,
    TaskIn,
    TaskOut,
    TaskUpdate,
)

router = APIRouter(prefix="/hotels/{hotel_id}", tags=["housekeeping"])

View = hotel_ctx(P.HOUSEKEEPING_VIEW)
Update = hotel_ctx(P.HOUSEKEEPING_UPDATE)
Assign = hotel_ctx(P.HOUSEKEEPING_ASSIGN)


class RoomStatusIn(InputModel):
    status: Literal["clean", "dirty", "in_progress", "inspected"]


@router.get("/housekeeping/tasks", response_model=list[TaskOut])
async def list_tasks(
    ctx: View,
    db: DB,
    day: date | None = None,
    assigned_to: Annotated[str | None, Query(description="a user id, or 'me'")] = None,
    unassigned: bool = False,
    status_: Annotated[
        Literal["pending", "in_progress", "done", "inspected", "skipped"] | None, Query(alias="status")
    ] = None,
):
    who = ctx.actor.user_id if assigned_to == "me" else (uuid.UUID(assigned_to) if assigned_to else None)
    return await service.list_tasks(db, ctx, day=day, assigned_to=who, unassigned=unassigned, status=status_)


@router.post("/housekeeping/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def create_task(body: TaskIn, ctx: Assign, db: DB):
    return await service.task_out(db, ctx, await service.create_task(db, ctx, body))


@router.patch("/housekeeping/tasks/{task_id}", response_model=TaskOut)
async def update_task(task_id: uuid.UUID, body: TaskUpdate, ctx: Assign, db: DB):
    return await service.task_out(db, ctx, await service.update_task(db, ctx, task_id, body))


@router.delete("/housekeeping/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: uuid.UUID, ctx: Assign, db: DB):
    await service.delete_task(db, ctx, task_id)


@router.post("/housekeeping/tasks/assign")
async def assign(body: AssignIn, ctx: Assign, db: DB):
    return {"updated": await service.assign_tasks(db, ctx, body.task_ids, body.user_id)}


@router.post("/housekeeping/tasks/{task_id}/{action}", response_model=TaskOut)
async def act(
    task_id: uuid.UUID,
    action: Literal["start", "complete", "skip", "inspect", "reject", "reopen"],
    body: ActionIn,
    ctx: Update,
    db: DB,
):
    return await service.task_out(db, ctx, await service.act(db, ctx, task_id, action, body.reason))


@router.post("/housekeeping/prepare", response_model=PrepareOut)
async def prepare(ctx: Assign, db: DB):
    return await service.prepare_day(db, ctx)


@router.get("/housekeeping/staff", response_model=list[StaffOut])
async def staff(ctx: View, db: DB):
    return await service.staff(db, ctx.hotel_id)


@router.post("/rooms/{room_id}/housekeeping-status")
async def set_room_status(room_id: uuid.UUID, body: RoomStatusIn, ctx: Update, db: DB):
    room = await service.set_status_manual(db, ctx, room_id, body.status)
    return {"room_id": room.id, "housekeeping_status": room.housekeeping_status, "version": room.version}


@router.get("/rooms/{room_id}/status-history", response_model=list[StatusChangeOut])
async def status_history(
    room_id: uuid.UUID, ctx: View, db: DB, limit: Annotated[int, Query(ge=1, le=200)] = 50
):
    return await service.room_history(db, ctx, room_id, limit)
