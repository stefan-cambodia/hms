from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.core.permissions import P
from app.modules.auth.deps import DB, hotel_ctx
from app.modules.facilities import service
from app.modules.facilities.schemas import (
    FacilityIn,
    FacilityOut,
    FacilityUpdate,
    ServiceIn,
    ServiceOut,
    ServiceUpdate,
    TaxRateIn,
    TaxRateOut,
    TaxRateUpdate,
)

router = APIRouter(prefix="/hotels/{hotel_id}", tags=["facilities"])

View = hotel_ctx(P.HOTEL_VIEW)
ManageFacilities = hotel_ctx(P.CONFIG_FACILITIES)
ManageTaxes = hotel_ctx(P.CONFIG_TAXES)


@router.get("/facilities", response_model=list[FacilityOut])
async def list_facilities(ctx: View, db: DB):
    return await service.list_facilities(db, ctx.hotel_id)


@router.post("/facilities", response_model=FacilityOut, status_code=status.HTTP_201_CREATED)
async def create_facility(body: FacilityIn, ctx: ManageFacilities, db: DB):
    return await service.create_facility(db, ctx, body)


@router.patch("/facilities/{facility_id}", response_model=FacilityOut)
async def update_facility(facility_id: uuid.UUID, body: FacilityUpdate, ctx: ManageFacilities, db: DB):
    return await service.update_facility(db, ctx, facility_id, body)


@router.delete("/facilities/{facility_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_facility(facility_id: uuid.UUID, ctx: ManageFacilities, db: DB):
    await service.delete_facility(db, ctx, facility_id)


@router.get("/services", response_model=list[ServiceOut])
async def list_services(ctx: View, db: DB):
    return await service.list_services(db, ctx.hotel_id)


@router.post("/services", response_model=ServiceOut, status_code=status.HTTP_201_CREATED)
async def create_service(body: ServiceIn, ctx: ManageFacilities, db: DB):
    return await service.create_service(db, ctx, body)


@router.patch("/services/{service_id}", response_model=ServiceOut)
async def update_service(service_id: uuid.UUID, body: ServiceUpdate, ctx: ManageFacilities, db: DB):
    return await service.update_service(db, ctx, service_id, body)


@router.delete("/services/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_service(service_id: uuid.UUID, ctx: ManageFacilities, db: DB):
    await service.delete_service(db, ctx, service_id)


@router.get("/tax-rates", response_model=list[TaxRateOut])
async def list_tax_rates(ctx: View, db: DB):
    return await service.list_tax_rates(db, ctx.hotel_id)


@router.post("/tax-rates", response_model=TaxRateOut, status_code=status.HTTP_201_CREATED)
async def create_tax_rate(body: TaxRateIn, ctx: ManageTaxes, db: DB):
    return await service.create_tax_rate(db, ctx, body)


@router.patch("/tax-rates/{tax_id}", response_model=TaxRateOut)
async def update_tax_rate(tax_id: uuid.UUID, body: TaxRateUpdate, ctx: ManageTaxes, db: DB):
    return await service.update_tax_rate(db, ctx, tax_id, body)


@router.delete("/tax-rates/{tax_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tax_rate(tax_id: uuid.UUID, ctx: ManageTaxes, db: DB):
    await service.delete_tax_rate(db, ctx, tax_id)
