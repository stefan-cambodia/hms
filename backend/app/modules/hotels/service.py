from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crud
from app.core.context import Actor, HotelContext
from app.core.errors import Forbidden, NotFound, ValidationFailed, field_error, register_constraint
from app.core.refdata import is_country, is_currency, is_timezone
from app.modules.hotels.models import Building, Floor, Hotel
from app.modules.hotels.schemas import (
    SOCIAL_KEYS,
    BuildingIn,
    BuildingUpdate,
    FloorIn,
    FloorUpdate,
    HotelCreate,
    HotelUpdate,
)

register_constraint("uq_hotels_organization_id_code", "HOTEL_CODE_EXISTS", field="code")
register_constraint("uq_buildings_hotel_id_code", "BUILDING_CODE_EXISTS", field="code")
register_constraint("uq_floors_building_id_level", "FLOOR_LEVEL_EXISTS", field="level")

HOTEL_FIELDS = (
    "name",
    "legal_name",
    "description",
    "address_line1",
    "address_line2",
    "city",
    "region",
    "postal_code",
    "country_code",
    "latitude",
    "longitude",
    "phone",
    "email",
    "website",
    "social_links",
    "timezone",
    "default_language",
    "supported_languages",
    "currency_code",
    "check_in_time",
    "check_out_time",
    "tax_id",
    "billing_info",
    "policies",
    "is_active",
)
BUILDING_FIELDS = ("code", "name", "sort_order", "is_active")
FLOOR_FIELDS = ("building_id", "level", "name", "sort_order")


def _validate_reference_data(*, timezone: str | None, currency: str | None, country: str | None) -> None:
    errors = []
    if timezone is not None and not is_timezone(timezone):
        errors.append(field_error("timezone", "INVALID_TIMEZONE"))
    if currency is not None and not is_currency(currency):
        errors.append(field_error("currency_code", "INVALID_CURRENCY"))
    if country is not None and not is_country(country):
        errors.append(field_error("country_code", "INVALID_COUNTRY"))
    if errors:
        raise ValidationFailed("VALIDATION_FAILED", "Invalid reference data", fields=errors)


async def get_hotel(db: AsyncSession, hotel_id: uuid.UUID) -> Hotel:
    hotel = await db.get(Hotel, hotel_id)
    if hotel is None:
        raise NotFound("HOTEL_NOT_FOUND")
    return hotel


async def create_hotel(db: AsyncSession, actor: Actor, data: HotelCreate) -> Hotel:
    """Add another property to the organisation (multi-property)."""
    if not actor.is_superadmin:
        raise Forbidden("PERMISSION_DENIED")
    _validate_reference_data(timezone=data.timezone, currency=data.currency_code, country=data.country_code)
    from app.modules.hotels.bootstrap import seed_hotel_defaults

    hotel = Hotel(organization_id=actor.organization_id, version=1, **data.model_dump())
    db.add(hotel)
    await db.flush()
    await seed_hotel_defaults(db, hotel)
    ctx = HotelContext(actor=actor, hotel_id=hotel.id)
    return await crud.create(db, ctx, hotel, entity="hotel", fields=("code", "name"))


async def update_hotel(db: AsyncSession, ctx: HotelContext, data: HotelUpdate) -> Hotel:
    hotel = await get_hotel(db, ctx.hotel_id)
    changes: dict[str, Any] = data.model_dump(exclude_unset=True, exclude={"version"}, mode="python")
    if "website" in changes and changes["website"] is not None:
        changes["website"] = str(changes["website"])
    if "social_links" in changes and changes["social_links"] is not None:
        bad = [k for k in changes["social_links"] if k not in SOCIAL_KEYS]
        if bad:
            raise ValidationFailed(fields=[field_error("social_links", "INVALID_SOCIAL_NETWORK", key=bad[0])])
        changes["social_links"] = {
            k: v.strip()[:300] for k, v in changes["social_links"].items() if v and v.strip()
        }
    for key in (
        "name",
        "timezone",
        "currency_code",
        "default_language",
        "supported_languages",
        "check_in_time",
        "check_out_time",
        "description",
        "billing_info",
        "policies",
    ):
        if key in changes and changes[key] is None:
            raise ValidationFailed(fields=[field_error(key, "REQUIRED")])
    _validate_reference_data(
        timezone=changes.get("timezone"),
        currency=changes.get("currency_code"),
        country=changes.get("country_code"),
    )
    default_lang = changes.get("default_language", hotel.default_language)
    supported = changes.get("supported_languages", hotel.supported_languages)
    if "supported_languages" in changes:
        supported = list(dict.fromkeys(supported))  # dedupe, keep order
        changes["supported_languages"] = supported
    if default_lang not in supported:
        raise ValidationFailed(fields=[field_error("default_language", "DEFAULT_LANGUAGE_NOT_SUPPORTED")])
    return await crud.update(
        db, ctx, hotel, changes, version=data.version, entity="hotel", fields=HOTEL_FIELDS
    )


# --- Buildings ---------------------------------------------------------------


async def list_buildings(db: AsyncSession, hotel_id: uuid.UUID) -> list[Building]:
    rows = await db.scalars(
        select(Building).where(Building.hotel_id == hotel_id).order_by(Building.sort_order, Building.code)
    )
    return list(rows)


async def create_building(db: AsyncSession, ctx: HotelContext, data: BuildingIn) -> Building:
    obj = Building(hotel_id=ctx.hotel_id, version=1, **data.model_dump())
    return await crud.create(db, ctx, obj, entity="building", fields=BUILDING_FIELDS)


async def update_building(
    db: AsyncSession, ctx: HotelContext, building_id: uuid.UUID, data: BuildingUpdate
) -> Building:
    obj = await crud.get_scoped(db, Building, ctx.hotel_id, building_id, code="BUILDING_NOT_FOUND")
    changes = data.model_dump(exclude_unset=True, exclude={"version"})
    return await crud.update(
        db, ctx, obj, changes, version=data.version, entity="building", fields=BUILDING_FIELDS
    )


async def delete_building(db: AsyncSession, ctx: HotelContext, building_id: uuid.UUID) -> None:
    obj = await crud.get_scoped(db, Building, ctx.hotel_id, building_id, code="BUILDING_NOT_FOUND")
    await crud.delete(db, ctx, obj, entity="building", fields=BUILDING_FIELDS)


# --- Floors ------------------------------------------------------------------


async def list_floors(db: AsyncSession, hotel_id: uuid.UUID) -> list[Floor]:
    rows = await db.scalars(
        select(Floor).where(Floor.hotel_id == hotel_id).order_by(Floor.building_id, Floor.level)
    )
    return list(rows)


async def create_floor(db: AsyncSession, ctx: HotelContext, data: FloorIn) -> Floor:
    await crud.get_scoped(db, Building, ctx.hotel_id, data.building_id, code="BUILDING_NOT_FOUND")
    obj = Floor(hotel_id=ctx.hotel_id, version=1, **data.model_dump())
    return await crud.create(db, ctx, obj, entity="floor", fields=FLOOR_FIELDS)


async def update_floor(db: AsyncSession, ctx: HotelContext, floor_id: uuid.UUID, data: FloorUpdate) -> Floor:
    obj = await crud.get_scoped(db, Floor, ctx.hotel_id, floor_id, code="FLOOR_NOT_FOUND")
    changes = data.model_dump(exclude_unset=True, exclude={"version"})
    return await crud.update(db, ctx, obj, changes, version=data.version, entity="floor", fields=FLOOR_FIELDS)


async def delete_floor(db: AsyncSession, ctx: HotelContext, floor_id: uuid.UUID) -> None:
    obj = await crud.get_scoped(db, Floor, ctx.hotel_id, floor_id, code="FLOOR_NOT_FOUND")
    await crud.delete(db, ctx, obj, entity="floor", fields=FLOOR_FIELDS)
