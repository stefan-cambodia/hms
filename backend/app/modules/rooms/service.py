from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit, crud, events
from app.core.context import HotelContext
from app.core.errors import Conflict, ValidationFailed, field_error, register_constraint
from app.modules.hotels.models import Building, Floor
from app.modules.rooms.models import Amenity, Room, RoomType
from app.modules.rooms.schemas import (
    AmenityIn,
    AmenityUpdate,
    RoomBulkIn,
    RoomIn,
    RoomOut,
    RoomTypeIn,
    RoomTypeOut,
    RoomTypeUpdate,
    RoomUpdate,
    occupancy_error,
)

register_constraint("uq_amenities_hotel_id_code", "AMENITY_CODE_EXISTS", field="code")
register_constraint("uq_room_types_hotel_id_code", "ROOM_TYPE_CODE_EXISTS", field="code")
register_constraint("uq_rooms_hotel_id_number", "ROOM_NUMBER_EXISTS", field="number")
register_constraint("ck_room_types_max_ge_base", "MAX_OCCUPANCY_BELOW_BASE", 422, "max_occupancy")
register_constraint("ck_room_types_max_adults", "MAX_ADULTS_ABOVE_MAX_OCCUPANCY", 422, "max_adults")
register_constraint("ck_room_types_max_children", "MAX_CHILDREN_ABOVE_MAX_OCCUPANCY", 422, "max_children")

AMENITY_FIELDS = ("code", "name", "icon", "scope", "sort_order", "is_active")
ROOM_TYPE_FIELDS = (
    "code",
    "name",
    "description",
    "base_occupancy",
    "max_occupancy",
    "max_adults",
    "max_children",
    "bed_configuration",
    "size_sqm",
    "base_price",
    "extra_adult_price",
    "extra_child_price",
    "color",
    "sort_order",
    "is_active",
    "amenities",
)
ROOM_FIELDS = (
    "room_type_id",
    "building_id",
    "floor_id",
    "number",
    "name",
    "max_occupancy",
    "bed_configuration",
    "size_sqm",
    "bathroom",
    "has_balcony",
    "view",
    "base_price",
    "notes",
    "sort_order",
    "is_active",
    "amenities",
)


async def _amenities(db: AsyncSession, hotel_id: uuid.UUID, ids: list[uuid.UUID]) -> list[Amenity]:
    if not ids:
        return []
    unique = list(dict.fromkeys(ids))
    found = list(
        await db.scalars(select(Amenity).where(Amenity.hotel_id == hotel_id, Amenity.id.in_(unique)))
    )
    if len(found) != len(unique):
        raise ValidationFailed(fields=[field_error("amenity_ids", "AMENITY_NOT_FOUND")])
    order = {a: i for i, a in enumerate(unique)}
    return sorted(found, key=lambda a: order[a.id])


# --- Amenities ---------------------------------------------------------------


async def list_amenities(db: AsyncSession, hotel_id: uuid.UUID) -> list[Amenity]:
    return list(
        await db.scalars(
            select(Amenity).where(Amenity.hotel_id == hotel_id).order_by(Amenity.sort_order, Amenity.code)
        )
    )


async def create_amenity(db: AsyncSession, ctx: HotelContext, data: AmenityIn) -> Amenity:
    obj = Amenity(hotel_id=ctx.hotel_id, version=1, **data.model_dump())
    return await crud.create(db, ctx, obj, entity="amenity", fields=AMENITY_FIELDS)


async def update_amenity(
    db: AsyncSession, ctx: HotelContext, amenity_id: uuid.UUID, data: AmenityUpdate
) -> Amenity:
    obj = await crud.get_scoped(db, Amenity, ctx.hotel_id, amenity_id, code="AMENITY_NOT_FOUND")
    changes = data.model_dump(exclude_unset=True, exclude={"version"})
    _reject_nulls(changes, ("code", "name", "scope", "sort_order", "is_active"))
    return await crud.update(
        db, ctx, obj, changes, version=data.version, entity="amenity", fields=AMENITY_FIELDS
    )


async def delete_amenity(db: AsyncSession, ctx: HotelContext, amenity_id: uuid.UUID) -> None:
    obj = await crud.get_scoped(db, Amenity, ctx.hotel_id, amenity_id, code="AMENITY_NOT_FOUND")
    await crud.delete(db, ctx, obj, entity="amenity", fields=AMENITY_FIELDS)


# --- Room types --------------------------------------------------------------


def room_type_out(obj: RoomType, room_count: int = 0) -> RoomTypeOut:
    out = RoomTypeOut.model_validate(obj)
    out.amenity_ids = [a.id for a in obj.amenities]
    out.room_count = room_count
    return out


async def _room_counts(db: AsyncSession, hotel_id: uuid.UUID) -> dict[uuid.UUID, int]:
    rows = await db.execute(
        select(Room.room_type_id, func.count())
        .where(Room.hotel_id == hotel_id, Room.is_active.is_(True))
        .group_by(Room.room_type_id)
    )
    return {rt: n for rt, n in rows}


async def list_room_types(db: AsyncSession, hotel_id: uuid.UUID) -> list[RoomTypeOut]:
    counts = await _room_counts(db, hotel_id)
    rows = await db.scalars(
        select(RoomType).where(RoomType.hotel_id == hotel_id).order_by(RoomType.sort_order, RoomType.code)
    )
    return [room_type_out(rt, counts.get(rt.id, 0)) for rt in rows]


async def get_room_type(db: AsyncSession, hotel_id: uuid.UUID, rt_id: uuid.UUID) -> RoomTypeOut:
    obj = await crud.get_scoped(db, RoomType, hotel_id, rt_id, code="ROOM_TYPE_NOT_FOUND")
    return room_type_out(obj, (await _room_counts(db, hotel_id)).get(obj.id, 0))


def _check_occupancy(values: dict[str, int]) -> None:
    error = occupancy_error(**values)
    if error:
        field = {
            "MAX_OCCUPANCY_BELOW_BASE": "max_occupancy",
            "MAX_ADULTS_ABOVE_MAX_OCCUPANCY": "max_adults",
            "MAX_CHILDREN_ABOVE_MAX_OCCUPANCY": "max_children",
        }[error]
        raise ValidationFailed(error, error, fields=[field_error(field, error)])


def _reject_nulls(changes: dict[str, Any], keys: tuple[str, ...]) -> None:
    for k in keys:
        if k in changes and changes[k] is None:
            raise ValidationFailed(fields=[field_error(k, "REQUIRED")])


async def create_room_type(db: AsyncSession, ctx: HotelContext, data: RoomTypeIn) -> RoomTypeOut:
    values = data.model_dump(exclude={"amenity_ids"})
    _check_occupancy(
        {k: values[k] for k in ("base_occupancy", "max_occupancy", "max_adults", "max_children")}
    )
    obj = RoomType(hotel_id=ctx.hotel_id, version=1, **values)
    obj.amenities = await _amenities(db, ctx.hotel_id, data.amenity_ids)
    obj = await crud.create(db, ctx, obj, entity="room_type", fields=ROOM_TYPE_FIELDS)
    return room_type_out(obj)


async def update_room_type(
    db: AsyncSession, ctx: HotelContext, rt_id: uuid.UUID, data: RoomTypeUpdate
) -> RoomTypeOut:
    obj = await crud.get_scoped(db, RoomType, ctx.hotel_id, rt_id, code="ROOM_TYPE_NOT_FOUND")
    changes = data.model_dump(exclude_unset=True, exclude={"version", "amenity_ids"})
    _reject_nulls(
        changes,
        (
            "code",
            "name",
            "description",
            "base_occupancy",
            "max_occupancy",
            "max_adults",
            "max_children",
            "bed_configuration",
            "base_price",
            "extra_adult_price",
            "extra_child_price",
            "sort_order",
            "is_active",
        ),
    )
    occ = {
        k: changes.get(k, getattr(obj, k))
        for k in ("base_occupancy", "max_occupancy", "max_adults", "max_children")
    }
    _check_occupancy(occ)
    if data.amenity_ids is not None:
        changes["amenities"] = await _amenities(db, ctx.hotel_id, data.amenity_ids)
    obj = await crud.update(
        db, ctx, obj, changes, version=data.version, entity="room_type", fields=ROOM_TYPE_FIELDS
    )
    return room_type_out(obj, (await _room_counts(db, ctx.hotel_id)).get(obj.id, 0))


async def delete_room_type(db: AsyncSession, ctx: HotelContext, rt_id: uuid.UUID) -> None:
    obj = await crud.get_scoped(db, RoomType, ctx.hotel_id, rt_id, code="ROOM_TYPE_NOT_FOUND")
    in_use = await db.scalar(select(func.count()).where(Room.room_type_id == rt_id))
    if in_use:
        raise Conflict("ROOM_TYPE_IN_USE", "Room category still has rooms", params={"rooms": int(in_use)})
    await crud.delete(db, ctx, obj, entity="room_type", fields=ROOM_TYPE_FIELDS)


# --- Rooms -------------------------------------------------------------------


def room_out(obj: Room) -> RoomOut:
    out = RoomOut.model_validate(obj)
    out.amenity_ids = [a.id for a in obj.amenities]
    return out


async def _validate_placement(
    db: AsyncSession,
    hotel_id: uuid.UUID,
    room_type_id: uuid.UUID | None,
    building_id: uuid.UUID | None,
    floor_id: uuid.UUID | None,
) -> uuid.UUID | None:
    """Check references belong to this hotel; return the effective building_id."""
    if room_type_id is not None:
        await crud.get_scoped(db, RoomType, hotel_id, room_type_id, code="ROOM_TYPE_NOT_FOUND")
    if building_id is not None:
        await crud.get_scoped(db, Building, hotel_id, building_id, code="BUILDING_NOT_FOUND")
    if floor_id is not None:
        floor = await crud.get_scoped(db, Floor, hotel_id, floor_id, code="FLOOR_NOT_FOUND")
        if building_id is None:
            return floor.building_id
        if floor.building_id != building_id:
            raise ValidationFailed(
                "FLOOR_NOT_IN_BUILDING",
                "Floor belongs to another building",
                fields=[field_error("floor_id", "FLOOR_NOT_IN_BUILDING")],
            )
    return building_id


async def list_rooms(
    db: AsyncSession,
    hotel_id: uuid.UUID,
    *,
    room_type_id: uuid.UUID | None = None,
    building_id: uuid.UUID | None = None,
    floor_id: uuid.UUID | None = None,
    is_active: bool | None = None,
    q: str | None = None,
) -> list[RoomOut]:
    stmt = select(Room).where(Room.hotel_id == hotel_id)
    if room_type_id:
        stmt = stmt.where(Room.room_type_id == room_type_id)
    if building_id:
        stmt = stmt.where(Room.building_id == building_id)
    if floor_id:
        stmt = stmt.where(Room.floor_id == floor_id)
    if is_active is not None:
        stmt = stmt.where(Room.is_active.is_(is_active))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(Room.number.ilike(like) | Room.name.ilike(like))
    stmt = stmt.order_by(Room.sort_order, func.length(Room.number), Room.number)
    return [room_out(r) for r in await db.scalars(stmt)]


async def get_room(db: AsyncSession, hotel_id: uuid.UUID, room_id: uuid.UUID) -> RoomOut:
    return room_out(await crud.get_scoped(db, Room, hotel_id, room_id, code="ROOM_NOT_FOUND"))


async def create_room(db: AsyncSession, ctx: HotelContext, data: RoomIn) -> RoomOut:
    building_id = await _validate_placement(
        db, ctx.hotel_id, data.room_type_id, data.building_id, data.floor_id
    )
    values = data.model_dump(exclude={"amenity_ids"})
    values["building_id"] = building_id
    obj = Room(hotel_id=ctx.hotel_id, version=1, **values)
    obj.amenities = await _amenities(db, ctx.hotel_id, data.amenity_ids)
    obj = await crud.create(db, ctx, obj, entity="room", fields=ROOM_FIELDS)
    return room_out(obj)


async def bulk_create_rooms(db: AsyncSession, ctx: HotelContext, data: RoomBulkIn) -> list[RoomOut]:
    building_id = await _validate_placement(
        db, ctx.hotel_id, data.room_type_id, data.building_id, data.floor_id
    )
    numbers = data.numbers()
    existing = list(
        await db.scalars(select(Room.number).where(Room.hotel_id == ctx.hotel_id, Room.number.in_(numbers)))
    )
    if existing:
        raise Conflict(
            "ROOM_NUMBER_EXISTS",
            "Some room numbers already exist",
            params={"numbers": ", ".join(sorted(existing)[:20])},
        )
    amenities = await _amenities(db, ctx.hotel_id, data.amenity_ids)
    rooms = []
    for number in numbers:
        room = Room(
            hotel_id=ctx.hotel_id,
            room_type_id=data.room_type_id,
            building_id=building_id,
            floor_id=data.floor_id,
            number=number,
            sort_order=0,
            version=1,
        )
        room.amenities = list(amenities)
        db.add(room)
        rooms.append(room)
    await db.flush()
    audit.record(
        db,
        ctx.actor,
        "room.bulk_create",
        "room",
        None,
        hotel_id=ctx.hotel_id,
        changes={"numbers": [None, numbers], "room_type_id": [None, data.room_type_id]},
    )
    await events.emit(
        db,
        hotel_id=ctx.hotel_id,
        entity="room",
        action="created",
        actor=ctx.actor,
        extra={"count": len(rooms)},
    )
    await db.commit()
    return [room_out(r) for r in rooms]


async def _stays_from_tonight(db: AsyncSession, hotel_id: uuid.UUID, room_id: uuid.UUID) -> int:
    """Stays in the room tonight or later (a room taken out of service must be free)."""
    from app.modules.hotels.models import Hotel
    from app.modules.reservations.models import RoomAllocation
    from app.modules.reservations.service import hotel_today

    hotel = await db.get(Hotel, hotel_id)
    assert hotel is not None
    tonight = hotel_today(hotel)
    return int(
        await db.scalar(
            select(func.count())
            .select_from(RoomAllocation)
            .where(
                RoomAllocation.room_id == room_id,
                RoomAllocation.room_block_id.is_(None),
                func.upper(RoomAllocation.period) > tonight,
            )
        )
        or 0
    )


async def update_room(db: AsyncSession, ctx: HotelContext, room_id: uuid.UUID, data: RoomUpdate) -> RoomOut:
    obj = await crud.get_scoped(db, Room, ctx.hotel_id, room_id, code="ROOM_NOT_FOUND")
    changes = data.model_dump(exclude_unset=True, exclude={"version", "amenity_ids"})
    _reject_nulls(changes, ("room_type_id", "number", "has_balcony", "sort_order", "is_active"))
    # Taking a room out of service (its history is kept, see RoomServicePeriod):
    # guests in it tonight or booked into it later are moved first.
    if changes.get("is_active") is False and obj.is_active:
        stays = await _stays_from_tonight(db, ctx.hotel_id, obj.id)
        if stays:
            raise Conflict("ROOM_HAS_STAYS", "Room has stays from tonight on", params={"count": stays})
    building_id = changes.get("building_id", obj.building_id)
    floor_id = changes.get("floor_id", obj.floor_id)
    if {"room_type_id", "building_id", "floor_id"} & changes.keys():
        effective = await _validate_placement(
            db, ctx.hotel_id, changes.get("room_type_id"), building_id, floor_id
        )
        changes["building_id"] = effective
    if data.amenity_ids is not None:
        changes["amenities"] = await _amenities(db, ctx.hotel_id, data.amenity_ids)
    obj = await crud.update(db, ctx, obj, changes, version=data.version, entity="room", fields=ROOM_FIELDS)
    return room_out(obj)


async def delete_room(db: AsyncSession, ctx: HotelContext, room_id: uuid.UUID) -> None:
    """Hard delete is only possible while the room has no history (enforced by
    foreign keys from reservations); otherwise deactivate it instead."""
    obj = await crud.get_scoped(db, Room, ctx.hotel_id, room_id, code="ROOM_NOT_FOUND")
    await crud.delete(db, ctx, obj, entity="room", fields=ROOM_FIELDS)
