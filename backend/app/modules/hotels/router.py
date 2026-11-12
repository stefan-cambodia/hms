from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.core.permissions import P
from app.modules.auth.deps import DB, Auth, hotel_ctx
from app.modules.hotels import service
from app.modules.hotels.schemas import (
    BuildingIn,
    BuildingOut,
    BuildingUpdate,
    FloorIn,
    FloorOut,
    FloorUpdate,
    HotelCreate,
    HotelOut,
    HotelUpdate,
)

router = APIRouter(tags=["hotels"])

View = hotel_ctx(P.HOTEL_VIEW)
ManageHotel = hotel_ctx(P.CONFIG_HOTEL)
ManageRooms = hotel_ctx(P.CONFIG_ROOMS)


@router.post("/hotels", response_model=HotelOut, status_code=status.HTTP_201_CREATED)
async def create_hotel(body: HotelCreate, auth: Auth, db: DB):
    return await service.create_hotel(db, auth.actor, body)


@router.get("/hotels/{hotel_id}", response_model=HotelOut)
async def get_hotel(ctx: View, db: DB):
    return await service.get_hotel(db, ctx.hotel_id)


@router.patch("/hotels/{hotel_id}", response_model=HotelOut)
async def update_hotel(body: HotelUpdate, ctx: ManageHotel, db: DB):
    return await service.update_hotel(db, ctx, body)


@router.get("/hotels/{hotel_id}/buildings", response_model=list[BuildingOut])
async def list_buildings(ctx: View, db: DB):
    return await service.list_buildings(db, ctx.hotel_id)


@router.post("/hotels/{hotel_id}/buildings", response_model=BuildingOut, status_code=status.HTTP_201_CREATED)
async def create_building(body: BuildingIn, ctx: ManageRooms, db: DB):
    return await service.create_building(db, ctx, body)


@router.patch("/hotels/{hotel_id}/buildings/{building_id}", response_model=BuildingOut)
async def update_building(building_id: uuid.UUID, body: BuildingUpdate, ctx: ManageRooms, db: DB):
    return await service.update_building(db, ctx, building_id, body)


@router.delete("/hotels/{hotel_id}/buildings/{building_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_building(building_id: uuid.UUID, ctx: ManageRooms, db: DB):
    await service.delete_building(db, ctx, building_id)


@router.get("/hotels/{hotel_id}/floors", response_model=list[FloorOut])
async def list_floors(ctx: View, db: DB):
    return await service.list_floors(db, ctx.hotel_id)


@router.post("/hotels/{hotel_id}/floors", response_model=FloorOut, status_code=status.HTTP_201_CREATED)
async def create_floor(body: FloorIn, ctx: ManageRooms, db: DB):
    return await service.create_floor(db, ctx, body)


@router.patch("/hotels/{hotel_id}/floors/{floor_id}", response_model=FloorOut)
async def update_floor(floor_id: uuid.UUID, body: FloorUpdate, ctx: ManageRooms, db: DB):
    return await service.update_floor(db, ctx, floor_id, body)


@router.delete("/hotels/{hotel_id}/floors/{floor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_floor(floor_id: uuid.UUID, ctx: ManageRooms, db: DB):
    await service.delete_floor(db, ctx, floor_id)
