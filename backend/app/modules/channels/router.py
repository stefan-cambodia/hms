from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Query, Response, status

from app.core.permissions import P
from app.modules.auth.deps import DB, hotel_ctx
from app.modules.channels import service
from app.modules.channels.schemas import (
    BookingOut,
    ConnectionIn,
    ConnectionOut,
    ConnectionUpdate,
    DismissIn,
    MappingsIn,
    MappingsOut,
    MessageDetailOut,
    MessageOut,
    ProductOut,
    TestOut,
)
from app.modules.channels.worker import worker

router = APIRouter(prefix="/hotels/{hotel_id}", tags=["channel manager"])

View = hotel_ctx(P.CHANNELS_VIEW)
Manage = hotel_ctx(P.CHANNELS_MANAGE)


@router.get("/channel-connections", response_model=list[ConnectionOut])
async def list_connections(ctx: View, db: DB):
    return await service.list_connections(db, ctx)


@router.post("/channel-connections", response_model=ConnectionOut, status_code=status.HTTP_201_CREATED)
async def create_connection(body: ConnectionIn, ctx: Manage, db: DB):
    return await service.create_connection(db, ctx, body)


@router.get("/channel-connections/{connection_id}", response_model=ConnectionOut)
async def get_connection(connection_id: uuid.UUID, ctx: View, db: DB):
    return await service.get_connection(db, ctx, connection_id)


@router.patch("/channel-connections/{connection_id}", response_model=ConnectionOut)
async def update_connection(connection_id: uuid.UUID, body: ConnectionUpdate, ctx: Manage, db: DB):
    result = await service.update_connection(db, ctx, connection_id, body)
    worker.wake()
    return result


@router.delete("/channel-connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(connection_id: uuid.UUID, ctx: Manage, db: DB):
    await service.delete_connection(db, ctx, connection_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/channel-connections/{connection_id}/test", response_model=TestOut)
async def test_connection(connection_id: uuid.UUID, ctx: Manage, db: DB):
    """A real call to the provider (never simulated)."""
    return await service.test_connection(db, ctx, connection_id)


@router.post("/channel-connections/{connection_id}/products", response_model=list[ProductOut])
async def fetch_products(connection_id: uuid.UUID, ctx: Manage, db: DB):
    """Retrieve the room and rate codes configured at the provider."""
    return await service.fetch_products(db, ctx, connection_id)


@router.get("/channel-connections/{connection_id}/mappings", response_model=MappingsOut)
async def get_mappings(connection_id: uuid.UUID, ctx: View, db: DB):
    return await service.get_mappings(db, ctx, connection_id)


@router.put("/channel-connections/{connection_id}/mappings", response_model=MappingsOut)
async def replace_mappings(connection_id: uuid.UUID, body: MappingsIn, ctx: Manage, db: DB):
    result = await service.replace_mappings(db, ctx, connection_id, body)
    worker.wake()
    return result


@router.post("/channel-connections/{connection_id}/sync", status_code=status.HTTP_202_ACCEPTED)
async def sync_now(connection_id: uuid.UUID, ctx: Manage, db: DB):
    await service.request_sync(db, ctx, connection_id)
    worker.wake()
    return {"status": "queued"}


@router.post("/channel-connections/{connection_id}/full-refresh", status_code=status.HTTP_202_ACCEPTED)
async def full_refresh(connection_id: uuid.UUID, ctx: Manage, db: DB):
    await service.request_full_refresh(db, ctx, connection_id)
    worker.wake()
    return {"status": "queued"}


@router.get("/channel-connections/{connection_id}/messages", response_model=list[MessageOut])
async def list_messages(
    connection_id: uuid.UUID,
    ctx: View,
    db: DB,
    errors_only: bool = False,
    limit: int = Query(100, ge=1, le=500),
):
    return await service.list_messages(db, ctx, connection_id, errors_only=errors_only, limit=limit)


@router.get("/channel-messages/{message_id}", response_model=MessageDetailOut)
async def get_message(message_id: int, ctx: Manage, db: DB):
    """Message bodies (card data and credentials already removed)."""
    return await service.get_message(db, ctx, message_id)


@router.get("/channel-bookings", response_model=list[BookingOut])
async def list_bookings(
    ctx: View,
    db: DB,
    status_: Literal["pending", "imported", "failed", "ignored"] | None = Query(None, alias="status"),
    attention: bool = False,
    limit: int = Query(100, ge=1, le=500),
):
    return await service.list_bookings(db, ctx, status=status_, attention=attention, limit=limit)


@router.post("/channel-bookings/{booking_id}/retry", response_model=BookingOut)
async def retry_booking(booking_id: uuid.UUID, ctx: Manage, db: DB):
    return await service.retry_booking(db, ctx, booking_id)


@router.post("/channel-bookings/{booking_id}/dismiss", response_model=BookingOut)
async def dismiss_booking(booking_id: uuid.UUID, body: DismissIn, ctx: Manage, db: DB):
    return await service.dismiss_booking(db, ctx, booking_id, body.reason)
