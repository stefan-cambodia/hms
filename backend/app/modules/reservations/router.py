from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Header, Query, Response, status

from app.core.permissions import P
from app.core.schemas import Page
from app.modules.auth.deps import DB, hotel_ctx
from app.modules.reservations import service
from app.modules.reservations.models import RoomBlock
from app.modules.reservations.schemas import (
    AssignRoomIn,
    AvailabilityOut,
    AvailableRoomOut,
    CalendarOut,
    CancelIn,
    ChangeDatesIn,
    ChangeRatePlanIn,
    FeePreviewOut,
    MoveStayIn,
    NightOut,
    NoShowIn,
    QuoteIn,
    QuoteOut,
    QuoteStayOut,
    ReservationEventOut,
    ReservationIn,
    ReservationListItem,
    ReservationOut,
    ReservationUpdate,
    RoomBlockIn,
    RoomBlockOut,
    TaxLineOut,
    VersionIn,
)

router = APIRouter(prefix="/hotels/{hotel_id}", tags=["reservations"])

View = hotel_ctx(P.RESERVATIONS_VIEW)
Create = hotel_ctx(P.RESERVATIONS_CREATE)
Edit = hotel_ctx(P.RESERVATIONS_EDIT)
CancelPerm = hotel_ctx(P.RESERVATIONS_CANCEL)
RoomsView = hotel_ctx(P.ROOMS_VIEW)
Block = hotel_ctx(P.ROOMS_BLOCK)


@router.post("/reservations/quote", response_model=QuoteOut)
async def quote(body: QuoteIn, ctx: View, db: DB):
    q = await service.quote(db, ctx, body.arrival, body.departure, body.rooms)
    return QuoteOut(
        currency=q.currency,
        accommodation_total=q.accommodation_total,
        tax_total=q.tax_added,
        grand_total=q.grand_total,
        taxes=[TaxLineOut.model_validate(t, from_attributes=True) for t in q.taxes],
        rooms=[
            [NightOut(night=n.night, price=n.price, price_source=n.source) for n in s.nights] for s in q.stays
        ],
        stays=[QuoteStayOut(rate_plan_id=s.rate_plan_id, issues=s.issues) for s in q.stays],
    )


@router.post("/reservations", response_model=ReservationOut, status_code=status.HTTP_201_CREATED)
async def create(
    body: ReservationIn,
    ctx: Create,
    db: DB,
    response: Response,
    idempotency_key: Annotated[str | None, Header(max_length=100)] = None,
):
    res, created = await service.create_reservation(db, ctx, body, idempotency_key)
    if not created:
        response.status_code = status.HTTP_200_OK
    return await service.reservation_out(db, res)


@router.get("/reservations", response_model=Page[ReservationListItem])
async def list_reservations(
    ctx: View,
    db: DB,
    start: date | None = None,
    end: date | None = None,
    status_: Annotated[str | None, Query(alias="status")] = None,
    q: str | None = None,
    guest_id: uuid.UUID | None = None,
    arrival: date | None = None,
    departure: date | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    items, total = await service.list_reservations(
        db,
        ctx,
        start=start,
        end=end,
        status=status_,
        q=q,
        limit=limit,
        offset=offset,
        guest_id=guest_id,
        arrival=arrival,
        departure=departure,
    )
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/reservations/{reservation_id}", response_model=ReservationOut)
async def get(reservation_id: uuid.UUID, ctx: View, db: DB):
    return await service.reservation_out(db, await service.get_reservation(db, ctx.hotel_id, reservation_id))


@router.get("/reservations/{reservation_id}/events", response_model=list[ReservationEventOut])
async def history(reservation_id: uuid.UUID, ctx: View, db: DB):
    return await service.reservation_events(db, ctx, reservation_id)


@router.patch("/reservations/{reservation_id}", response_model=ReservationOut)
async def update(reservation_id: uuid.UUID, body: ReservationUpdate, ctx: Edit, db: DB):
    return await service.reservation_out(db, await service.update_details(db, ctx, reservation_id, body))


@router.post("/reservations/{reservation_id}/rooms/{rr_id}/assign", response_model=ReservationOut)
async def assign(reservation_id: uuid.UUID, rr_id: uuid.UUID, body: AssignRoomIn, ctx: Edit, db: DB):
    return await service.reservation_out(db, await service.assign_room(db, ctx, reservation_id, rr_id, body))


@router.post("/reservations/{reservation_id}/rooms/{rr_id}/dates", response_model=ReservationOut)
async def change_dates(reservation_id: uuid.UUID, rr_id: uuid.UUID, body: ChangeDatesIn, ctx: Edit, db: DB):
    return await service.reservation_out(db, await service.change_dates(db, ctx, reservation_id, rr_id, body))


@router.post("/reservations/{reservation_id}/rooms/{rr_id}/move", response_model=ReservationOut)
async def move(reservation_id: uuid.UUID, rr_id: uuid.UUID, body: MoveStayIn, ctx: Edit, db: DB):
    res = await service.move_stay(
        db,
        ctx,
        reservation_id,
        rr_id,
        version=body.version,
        room_id=body.room_id,
        arrival=body.arrival,
        departure=body.departure,
    )
    return await service.reservation_out(db, res)


@router.get("/available-rooms", response_model=list[AvailableRoomOut])
async def available_rooms(
    ctx: View,
    db: DB,
    start: date,
    end: date,
    room_type_id: uuid.UUID | None = None,
    ignore_reservation_room: uuid.UUID | None = None,
):
    from app.core.errors import ValidationFailed

    if end <= start:
        raise ValidationFailed("INVALID_RANGE")
    return await service.available_rooms(
        db,
        ctx.hotel_id,
        start,
        end,
        room_type_id=room_type_id,
        ignore_reservation_room=ignore_reservation_room,
    )


@router.post("/reservations/{reservation_id}/rooms/{rr_id}/rate-plan", response_model=ReservationOut)
async def change_rate_plan(
    reservation_id: uuid.UUID, rr_id: uuid.UUID, body: ChangeRatePlanIn, ctx: Edit, db: DB
):
    res = await service.change_rate_plan(
        db,
        ctx,
        reservation_id,
        rr_id,
        version=body.version,
        rate_plan_id=body.rate_plan_id,
        override_restrictions=body.override_restrictions,
    )
    return await service.reservation_out(db, res)


@router.post("/reservations/{reservation_id}/confirm", response_model=ReservationOut)
async def confirm(reservation_id: uuid.UUID, body: VersionIn, ctx: Edit, db: DB):
    return await service.reservation_out(db, await service.confirm(db, ctx, reservation_id, body.version))


@router.get("/reservations/{reservation_id}/fee-preview", response_model=FeePreviewOut)
async def fee_preview(
    reservation_id: uuid.UUID, ctx: View, db: DB, action: Literal["cancel", "no_show"] = "cancel"
):
    return await service.fee_preview(db, ctx, reservation_id, action)


@router.post("/reservations/{reservation_id}/cancel", response_model=ReservationOut)
async def cancel(reservation_id: uuid.UUID, body: CancelIn, ctx: CancelPerm, db: DB):
    return await service.reservation_out(
        db, await service.cancel(db, ctx, reservation_id, body.version, body.reason, body.waive_fee)
    )


@router.post("/reservations/{reservation_id}/no-show", response_model=ReservationOut)
async def no_show(reservation_id: uuid.UUID, body: NoShowIn, ctx: Edit, db: DB):
    return await service.reservation_out(
        db, await service.mark_no_show(db, ctx, reservation_id, body.version, body.waive_fee)
    )


@router.get("/availability", response_model=list[AvailabilityOut])
async def availability(ctx: View, db: DB, start: date, end: date, room_type_id: uuid.UUID | None = None):
    from app.core.errors import ValidationFailed

    if end <= start or (end - start).days > 366:
        raise ValidationFailed("INVALID_RANGE", params={"max_days": 366})
    return await service.availability_out(db, ctx.hotel_id, start, end, room_type_id)


@router.get("/calendar", response_model=CalendarOut)
async def calendar(ctx: View, db: DB, start: date, end: date):
    return await service.calendar(db, ctx, start, end)


@router.get("/room-blocks", response_model=list[RoomBlockOut])
async def list_blocks(ctx: RoomsView, db: DB, start: date, end: date):
    from sqlalchemy import select

    rows = await db.scalars(
        select(RoomBlock)
        .where(RoomBlock.hotel_id == ctx.hotel_id, RoomBlock.start_date < end, RoomBlock.end_date > start)
        .order_by(RoomBlock.start_date)
    )
    return list(rows)


@router.post("/room-blocks", response_model=RoomBlockOut, status_code=status.HTTP_201_CREATED)
async def create_block(body: RoomBlockIn, ctx: Block, db: DB):
    return await service.create_block(db, ctx, body)


@router.delete("/room-blocks/{block_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_block(block_id: uuid.UUID, ctx: Block, db: DB):
    await service.delete_block(db, ctx, block_id)
