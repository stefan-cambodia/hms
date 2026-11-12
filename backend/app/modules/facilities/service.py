from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crud
from app.core.context import HotelContext
from app.core.errors import ValidationFailed, field_error, register_constraint
from app.modules.facilities.models import Facility, Service, TaxRate
from app.modules.facilities.schemas import (
    FacilityIn,
    FacilityUpdate,
    ServiceIn,
    ServiceUpdate,
    TaxRateIn,
    TaxRateUpdate,
)

register_constraint("uq_facilities_hotel_id_code", "FACILITY_CODE_EXISTS", field="code")
register_constraint("uq_services_hotel_id_code", "SERVICE_CODE_EXISTS", field="code")
register_constraint("uq_tax_rates_hotel_id_code", "TAX_CODE_EXISTS", field="code")
register_constraint("ck_tax_rates_percent_max", "TAX_PERCENT_ABOVE_100", 422, "rate")

FACILITY_FIELDS = (
    "code",
    "category",
    "name",
    "description",
    "opening_hours",
    "is_available",
    "pricing_mode",
    "price",
    "price_unit",
    "conditions",
    "notes",
    "sort_order",
    "is_active",
)
SERVICE_FIELDS = (
    "code",
    "name",
    "description",
    "facility_id",
    "price",
    "pricing_unit",
    "sort_order",
    "is_active",
)
TAX_FIELDS = ("code", "name", "kind", "rate", "is_inclusive", "applies_to", "sort_order", "is_active")


def _reject_nulls(changes: dict[str, Any], allowed_null: set[str]) -> None:
    for k, v in changes.items():
        if v is None and k not in allowed_null:
            raise ValidationFailed(fields=[field_error(k, "REQUIRED")])


def _check_facility_pricing(mode: str, price: Any) -> None:
    if mode == "paid" and price is None:
        raise ValidationFailed(
            "PRICE_REQUIRED", "Paid facilities need a price", fields=[field_error("price", "PRICE_REQUIRED")]
        )


def _check_tax(kind: str, rate: Any) -> None:
    if kind == "percent" and rate > 100:
        raise ValidationFailed(
            "TAX_PERCENT_ABOVE_100",
            "Percentage above 100",
            fields=[field_error("rate", "TAX_PERCENT_ABOVE_100")],
        )


def _hours_to_json(hours: dict[str, Any] | None) -> dict[str, Any] | None:
    if hours is None:
        return None
    return {day: [list(r) for r in ranges] for day, ranges in hours.items()}


# --- Facilities --------------------------------------------------------------


async def list_facilities(db: AsyncSession, hotel_id: uuid.UUID) -> list[Facility]:
    return list(
        await db.scalars(
            select(Facility).where(Facility.hotel_id == hotel_id).order_by(Facility.sort_order, Facility.code)
        )
    )


async def create_facility(db: AsyncSession, ctx: HotelContext, data: FacilityIn) -> Facility:
    _check_facility_pricing(data.pricing_mode, data.price)
    values = data.model_dump()
    values["opening_hours"] = _hours_to_json(values["opening_hours"])
    obj = Facility(hotel_id=ctx.hotel_id, version=1, **values)
    return await crud.create(db, ctx, obj, entity="facility", fields=FACILITY_FIELDS)


async def update_facility(
    db: AsyncSession, ctx: HotelContext, facility_id: uuid.UUID, data: FacilityUpdate
) -> Facility:
    obj = await crud.get_scoped(db, Facility, ctx.hotel_id, facility_id, code="FACILITY_NOT_FOUND")
    changes = data.model_dump(exclude_unset=True, exclude={"version"})
    _reject_nulls(changes, {"price", "price_unit", "notes"})
    _check_facility_pricing(changes.get("pricing_mode", obj.pricing_mode), changes.get("price", obj.price))
    if "opening_hours" in changes:
        changes["opening_hours"] = _hours_to_json(changes["opening_hours"])
    return await crud.update(
        db, ctx, obj, changes, version=data.version, entity="facility", fields=FACILITY_FIELDS
    )


async def delete_facility(db: AsyncSession, ctx: HotelContext, facility_id: uuid.UUID) -> None:
    obj = await crud.get_scoped(db, Facility, ctx.hotel_id, facility_id, code="FACILITY_NOT_FOUND")
    await crud.delete(db, ctx, obj, entity="facility", fields=FACILITY_FIELDS)


# --- Services ----------------------------------------------------------------


async def list_services(db: AsyncSession, hotel_id: uuid.UUID) -> list[Service]:
    return list(
        await db.scalars(
            select(Service).where(Service.hotel_id == hotel_id).order_by(Service.sort_order, Service.code)
        )
    )


async def create_service(db: AsyncSession, ctx: HotelContext, data: ServiceIn) -> Service:
    if data.facility_id:
        await crud.get_scoped(db, Facility, ctx.hotel_id, data.facility_id, code="FACILITY_NOT_FOUND")
    obj = Service(hotel_id=ctx.hotel_id, version=1, **data.model_dump())
    return await crud.create(db, ctx, obj, entity="service", fields=SERVICE_FIELDS)


async def update_service(
    db: AsyncSession, ctx: HotelContext, service_id: uuid.UUID, data: ServiceUpdate
) -> Service:
    obj = await crud.get_scoped(db, Service, ctx.hotel_id, service_id, code="SERVICE_NOT_FOUND")
    changes = data.model_dump(exclude_unset=True, exclude={"version"})
    _reject_nulls(changes, {"facility_id"})
    if changes.get("facility_id"):
        await crud.get_scoped(db, Facility, ctx.hotel_id, changes["facility_id"], code="FACILITY_NOT_FOUND")
    return await crud.update(
        db, ctx, obj, changes, version=data.version, entity="service", fields=SERVICE_FIELDS
    )


async def delete_service(db: AsyncSession, ctx: HotelContext, service_id: uuid.UUID) -> None:
    obj = await crud.get_scoped(db, Service, ctx.hotel_id, service_id, code="SERVICE_NOT_FOUND")
    await crud.delete(db, ctx, obj, entity="service", fields=SERVICE_FIELDS)


# --- Tax rates ---------------------------------------------------------------


async def list_tax_rates(db: AsyncSession, hotel_id: uuid.UUID) -> list[TaxRate]:
    return list(
        await db.scalars(
            select(TaxRate).where(TaxRate.hotel_id == hotel_id).order_by(TaxRate.sort_order, TaxRate.code)
        )
    )


async def create_tax_rate(db: AsyncSession, ctx: HotelContext, data: TaxRateIn) -> TaxRate:
    _check_tax(data.kind, data.rate)
    obj = TaxRate(hotel_id=ctx.hotel_id, version=1, **data.model_dump())
    return await crud.create(db, ctx, obj, entity="tax_rate", fields=TAX_FIELDS)


async def update_tax_rate(
    db: AsyncSession, ctx: HotelContext, tax_id: uuid.UUID, data: TaxRateUpdate
) -> TaxRate:
    obj = await crud.get_scoped(db, TaxRate, ctx.hotel_id, tax_id, code="TAX_RATE_NOT_FOUND")
    changes = data.model_dump(exclude_unset=True, exclude={"version"})
    _reject_nulls(changes, set())
    _check_tax(changes.get("kind", obj.kind), changes.get("rate", obj.rate))
    return await crud.update(
        db, ctx, obj, changes, version=data.version, entity="tax_rate", fields=TAX_FIELDS
    )


async def delete_tax_rate(db: AsyncSession, ctx: HotelContext, tax_id: uuid.UUID) -> None:
    obj = await crud.get_scoped(db, TaxRate, ctx.hotel_id, tax_id, code="TAX_RATE_NOT_FOUND")
    await crud.delete(db, ctx, obj, entity="tax_rate", fields=TAX_FIELDS)
