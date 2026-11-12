from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Query, status

from app.core.permissions import P
from app.core.schemas import Page, UpdateModel
from app.modules.auth.deps import DB, hotel_ctx
from app.modules.maintenance import service
from app.modules.maintenance.schemas import (
    BlockIn,
    CommentIn,
    RequestDetailOut,
    RequestIn,
    RequestOut,
    RequestUpdate,
    StatusIn,
    TechnicianOut,
)

router = APIRouter(prefix="/hotels/{hotel_id}", tags=["maintenance"])

View = hotel_ctx(P.MAINTENANCE_VIEW)
Report = hotel_ctx(P.MAINTENANCE_REPORT)
Manage = hotel_ctx(P.MAINTENANCE_MANAGE)


@router.get("/maintenance-requests", response_model=Page[RequestOut])
async def list_requests(
    ctx: View,
    db: DB,
    state: Literal["open", "closed", "all"] = "open",
    room_id: uuid.UUID | None = None,
    priority: Literal["low", "normal", "high", "urgent"] | None = None,
    assigned_to: Annotated[str | None, Query(description="a user id, or 'me'")] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    who = ctx.actor.user_id if assigned_to == "me" else (uuid.UUID(assigned_to) if assigned_to else None)
    items, total = await service.list_requests(
        db,
        ctx,
        state=state,
        room_id=room_id,
        priority=priority,
        assigned_to=who,
        q=q,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.post("/maintenance-requests", response_model=RequestDetailOut, status_code=status.HTTP_201_CREATED)
async def create_request(body: RequestIn, ctx: Report, db: DB):
    req = await service.create_request(db, ctx, body)
    return await service.request_out(db, ctx, req, detail=True)


@router.get("/maintenance-requests/{req_id}", response_model=RequestDetailOut)
async def get_request(req_id: uuid.UUID, ctx: View, db: DB):
    return await service.request_out(
        db, ctx, await service.get_request(db, ctx.hotel_id, req_id), detail=True
    )


@router.patch("/maintenance-requests/{req_id}", response_model=RequestDetailOut)
async def update_request(req_id: uuid.UUID, body: RequestUpdate, ctx: Manage, db: DB):
    req = await service.update_request(db, ctx, req_id, body)
    return await service.request_out(db, ctx, req, detail=True)


@router.post("/maintenance-requests/{req_id}/status", response_model=RequestDetailOut)
async def change_status(req_id: uuid.UUID, body: StatusIn, ctx: Manage, db: DB):
    req = await service.change_status(db, ctx, req_id, body)
    return await service.request_out(db, ctx, req, detail=True)


@router.post("/maintenance-requests/{req_id}/comments", response_model=RequestDetailOut)
async def add_comment(req_id: uuid.UUID, body: CommentIn, ctx: Report, db: DB):
    req = await service.add_comment(db, ctx, req_id, body.comment)
    return await service.request_out(db, ctx, req, detail=True)


@router.post("/maintenance-requests/{req_id}/block", response_model=RequestDetailOut)
async def set_block(req_id: uuid.UUID, body: BlockIn, ctx: Manage, db: DB):
    req = await service.set_block(db, ctx, req_id, body)
    return await service.request_out(db, ctx, req, detail=True)


@router.post("/maintenance-requests/{req_id}/release", response_model=RequestDetailOut)
async def release(req_id: uuid.UUID, body: UpdateModel, ctx: Manage, db: DB):
    req = await service.release(db, ctx, req_id, body.version)
    return await service.request_out(db, ctx, req, detail=True)


@router.get("/maintenance/technicians", response_model=list[TechnicianOut])
async def technicians(ctx: View, db: DB):
    return await service.technicians(db, ctx.hotel_id)
