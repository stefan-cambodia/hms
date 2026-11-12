from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.core.permissions import P
from app.modules.auth.deps import DB, hotel_ctx
from app.modules.rooms import service
from app.modules.rooms.schemas import (
    AmenityIn,
    AmenityOut,
    AmenityUpdate,
    RoomBulkIn,
    RoomIn,
    RoomOut,
    RoomTypeIn,
    RoomTypeOut,
    RoomTypeUpdate,
    RoomUpdate,
)

router = APIRouter(prefix="/hotels/{hotel_id}", tags=["rooms"])

View = hotel_ctx(P.HOTEL_VIEW)
Manage = hotel_ctx(P.CONFIG_ROOMS)


@router.get("/amenities", response_model=list[AmenityOut])
async def list_amenities(ctx: View, db: DB):
    return await service.list_amenities(db, ctx.hotel_id)


@router.post("/amenities", response_model=AmenityOut, status_code=status.HTTP_201_CREATED)
async def create_amenity(body: AmenityIn, ctx: Manage, db: DB):
    return await service.create_amenity(db, ctx, body)


@router.patch("/amenities/{amenity_id}", response_model=AmenityOut)
async def update_amenity(amenity_id: uuid.UUID, body: AmenityUpdate, ctx: Manage, db: DB):
    return await service.update_amenity(db, ctx, amenity_id, body)


@router.delete("/amenities/{amenity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_amenity(amenity_id: uuid.UUID, ctx: Manage, db: DB):
    await service.delete_amenity(db, ctx, amenity_id)


@router.get("/room-types", response_model=list[RoomTypeOut])
async def list_room_types(ctx: View, db: DB):
    return await service.list_room_types(db, ctx.hotel_id)


@router.get("/room-types/{room_type_id}", response_model=RoomTypeOut)
async def get_room_type(room_type_id: uuid.UUID, ctx: View, db: DB):
    return await service.get_room_type(db, ctx.hotel_id, room_type_id)


@router.post("/room-types", response_model=RoomTypeOut, status_code=status.HTTP_201_CREATED)
async def create_room_type(body: RoomTypeIn, ctx: Manage, db: DB):
    return await service.create_room_type(db, ctx, body)


@router.patch("/room-types/{room_type_id}", response_model=RoomTypeOut)
async def update_room_type(room_type_id: uuid.UUID, body: RoomTypeUpdate, ctx: Manage, db: DB):
    return await service.update_room_type(db, ctx, room_type_id, body)


@router.delete("/room-types/{room_type_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_room_type(room_type_id: uuid.UUID, ctx: Manage, db: DB):
    await service.delete_room_type(db, ctx, room_type_id)


@router.get("/rooms", response_model=list[RoomOut])
async def list_rooms(
    ctx: View,
    db: DB,
    room_type_id: uuid.UUID | None = None,
    building_id: uuid.UUID | None = None,
    floor_id: uuid.UUID | None = None,
    is_active: bool | None = None,
    q: str | None = None,
):
    return await service.list_rooms(
        db,
        ctx.hotel_id,
        room_type_id=room_type_id,
        building_id=building_id,
        floor_id=floor_id,
        is_active=is_active,
        q=q,
    )


@router.get("/rooms/{room_id}", response_model=RoomOut)
async def get_room(room_id: uuid.UUID, ctx: View, db: DB):
    return await service.get_room(db, ctx.hotel_id, room_id)


@router.post("/rooms", response_model=RoomOut, status_code=status.HTTP_201_CREATED)
async def create_room(body: RoomIn, ctx: Manage, db: DB):
    return await service.create_room(db, ctx, body)


@router.post("/rooms/bulk", response_model=list[RoomOut], status_code=status.HTTP_201_CREATED)
async def bulk_create_rooms(body: RoomBulkIn, ctx: Manage, db: DB):
    return await service.bulk_create_rooms(db, ctx, body)


@router.patch("/rooms/{room_id}", response_model=RoomOut)
async def update_room(room_id: uuid.UUID, body: RoomUpdate, ctx: Manage, db: DB):
    return await service.update_room(db, ctx, room_id, body)


@router.delete("/rooms/{room_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_room(room_id: uuid.UUID, ctx: Manage, db: DB):
    await service.delete_room(db, ctx, room_id)
