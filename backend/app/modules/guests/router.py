from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.core import audit, crud
from app.core.permissions import P
from app.core.schemas import Page
from app.modules.auth.deps import DB, hotel_ctx
from app.modules.guests import service
from app.modules.guests.models import Guest
from app.modules.guests.schemas import GuestDuplicateOut, GuestIn, GuestOut, GuestUpdate

router = APIRouter(prefix="/hotels/{hotel_id}/guests", tags=["guests"])

View = hotel_ctx(P.GUESTS_VIEW)
Edit = hotel_ctx(P.GUESTS_EDIT)


@router.get("", response_model=Page[GuestOut])
async def search(
    ctx: View,
    db: DB,
    q: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    items, total = await service.search_guests(db, ctx, q, limit=limit, offset=offset)
    return Page(items=[service.guest_out(g, ctx) for g in items], total=total, limit=limit, offset=offset)


@router.get("/duplicates", response_model=list[GuestDuplicateOut])
async def duplicates(
    ctx: View,
    db: DB,
    first_name: str,
    last_name: str,
    email: str | None = None,
    phone: str | None = None,
    exclude_id: uuid.UUID | None = None,
):
    return await service.find_duplicates(
        db, ctx, first_name=first_name, last_name=last_name, email=email, phone=phone, exclude_id=exclude_id
    )


@router.get("/{guest_id}", response_model=GuestOut)
async def get_guest(guest_id: uuid.UUID, ctx: View, db: DB):
    g = await crud.get_scoped(db, Guest, ctx.hotel_id, guest_id, code="GUEST_NOT_FOUND")
    if g.id_document_number is not None and ctx.has(P.GUESTS_VIEW_SENSITIVE):
        # Reads of identity data are audited.
        audit.record(db, ctx.actor, "guest.view_sensitive", "guest", g.id, hotel_id=ctx.hotel_id)
        await db.commit()
    return service.guest_out(g, ctx)


@router.post("", response_model=GuestOut, status_code=status.HTTP_201_CREATED)
async def create_guest(body: GuestIn, ctx: Edit, db: DB):
    return service.guest_out(await service.create_guest(db, ctx, body), ctx)


@router.patch("/{guest_id}", response_model=GuestOut)
async def update_guest(guest_id: uuid.UUID, body: GuestUpdate, ctx: Edit, db: DB):
    return service.guest_out(await service.update_guest(db, ctx, guest_id, body), ctx)
