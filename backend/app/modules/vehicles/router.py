from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Header, Query, Response, status

from app.core.permissions import P
from app.core.schemas import LanguageCode, UpdateModel
from app.modules.auth.deps import DB, hotel_ctx
from app.modules.vehicles import service
from app.modules.vehicles.schemas import (
    CancelIn,
    DiscountIn,
    PaymentIn,
    PickupIn,
    QuoteOut,
    RentalIn,
    RentalOut,
    RentalUpdate,
    ReturnIn,
    VehicleIn,
    VehicleOut,
    VehicleUpdate,
    VoidIn,
)

router = APIRouter(prefix="/hotels/{hotel_id}", tags=["vehicle rental"])

View = hotel_ctx(P.VEHICLES_VIEW)
Rent = hotel_ctx(P.VEHICLES_RENT)
Manage = hotel_ctx(P.VEHICLES_MANAGE)
IdempotencyKey = Annotated[str | None, Header(max_length=100)]


@router.get("/vehicles", response_model=list[VehicleOut])
async def list_vehicles(ctx: View, db: DB, start: datetime | None = None, end: datetime | None = None):
    return await service.list_vehicles(db, ctx, start, end)


@router.post("/vehicles", response_model=VehicleOut, status_code=status.HTTP_201_CREATED)
async def create_vehicle(body: VehicleIn, ctx: Manage, db: DB):
    return await service.vehicle_out(db, ctx, await service.create_vehicle(db, ctx, body))


@router.patch("/vehicles/{vehicle_id}", response_model=VehicleOut)
async def update_vehicle(vehicle_id: uuid.UUID, body: VehicleUpdate, ctx: Manage, db: DB):
    return await service.vehicle_out(db, ctx, await service.update_vehicle(db, ctx, vehicle_id, body))


@router.delete("/vehicles/{vehicle_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vehicle(vehicle_id: uuid.UUID, ctx: Manage, db: DB):
    await service.delete_vehicle(db, ctx, vehicle_id)


@router.get("/vehicle-rentals/quote", response_model=QuoteOut)
async def quote(
    ctx: View, db: DB, vehicle_id: uuid.UUID, start: datetime, end: datetime, with_driver: bool = False
):
    return await service.quote(db, ctx, vehicle_id, start, end, with_driver)


@router.get("/vehicle-rentals", response_model=list[RentalOut])
async def list_rentals(
    ctx: View,
    db: DB,
    status_: Annotated[
        Literal["active", "reserved", "out", "returned", "cancelled", "no_show"] | None, Query(alias="status")
    ] = None,
    start: datetime | None = None,
    end: datetime | None = None,
    vehicle_id: uuid.UUID | None = None,
):
    return await service.list_rentals(db, ctx, status=status_, start=start, end=end, vehicle_id=vehicle_id)


@router.post("/vehicle-rentals", response_model=RentalOut, status_code=status.HTTP_201_CREATED)
async def create_rental(body: RentalIn, ctx: Rent, db: DB, idempotency_key: IdempotencyKey = None):
    return await service.rental_out(db, await service.create_rental(db, ctx, body, idempotency_key))


@router.get("/vehicle-rentals/{rental_id}", response_model=RentalOut)
async def get_rental(rental_id: uuid.UUID, ctx: View, db: DB):
    return await service.rental_out(db, await service.get_rental(db, ctx.hotel_id, rental_id))


@router.patch("/vehicle-rentals/{rental_id}", response_model=RentalOut)
async def update_rental(rental_id: uuid.UUID, body: RentalUpdate, ctx: Rent, db: DB):
    return await service.rental_out(db, await service.update_rental(db, ctx, rental_id, body))


@router.post("/vehicle-rentals/{rental_id}/pickup", response_model=RentalOut)
async def pickup(rental_id: uuid.UUID, body: PickupIn, ctx: Rent, db: DB):
    return await service.rental_out(db, await service.pickup(db, ctx, rental_id, body))


@router.post("/vehicle-rentals/{rental_id}/return", response_model=RentalOut)
async def return_vehicle(rental_id: uuid.UUID, body: ReturnIn, ctx: Rent, db: DB):
    return await service.rental_out(db, await service.return_vehicle(db, ctx, rental_id, body))


@router.post("/vehicle-rentals/{rental_id}/deposit-returned", response_model=RentalOut)
async def deposit_returned(rental_id: uuid.UUID, body: UpdateModel, ctx: Rent, db: DB):
    return await service.rental_out(db, await service.return_deposit(db, ctx, rental_id, body.version))


@router.post("/vehicle-rentals/{rental_id}/discount", response_model=RentalOut)
async def discount(rental_id: uuid.UUID, body: DiscountIn, ctx: View, db: DB):
    return await service.rental_out(db, await service.set_discount(db, ctx, rental_id, body))


@router.post("/vehicle-rentals/{rental_id}/cancel", response_model=RentalOut)
async def cancel(rental_id: uuid.UUID, body: CancelIn, ctx: Rent, db: DB):
    return await service.rental_out(db, await service.close_unused(db, ctx, rental_id, "cancelled", body))


@router.post("/vehicle-rentals/{rental_id}/no-show", response_model=RentalOut)
async def no_show(rental_id: uuid.UUID, body: UpdateModel, ctx: Rent, db: DB):
    return await service.rental_out(db, await service.close_unused(db, ctx, rental_id, "no_show", body))


@router.post(
    "/vehicle-rentals/{rental_id}/payments", response_model=RentalOut, status_code=status.HTTP_201_CREATED
)
async def pay(
    rental_id: uuid.UUID, body: PaymentIn, ctx: Rent, db: DB, idempotency_key: IdempotencyKey = None
):
    rental, change = await service.record_payment(db, ctx, rental_id, body, idempotency_key)
    return await service.rental_out(db, rental, change)


@router.post("/vehicle-rentals/{rental_id}/payments/{payment_id}/void", response_model=RentalOut)
async def void_payment(rental_id: uuid.UUID, payment_id: uuid.UUID, body: VoidIn, ctx: View, db: DB):
    return await service.rental_out(
        db, await service.void_payment(db, ctx, rental_id, payment_id, body.reason)
    )


@router.get("/vehicle-rentals/{rental_id}/contract.pdf")
async def contract(
    rental_id: uuid.UUID, ctx: View, db: DB, language: Annotated[LanguageCode | None, Query()] = None
):
    content, name = await service.contract_pdf(db, ctx, rental_id, language)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{name}.pdf"', "Cache-Control": "no-store"},
    )
