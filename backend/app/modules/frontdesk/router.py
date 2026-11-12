from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter

from app.core.permissions import P
from app.modules.auth.deps import DB, hotel_ctx
from app.modules.frontdesk import service
from app.modules.frontdesk.schemas import (
    CheckInIn,
    CheckOutIn,
    FrontDeskOut,
    HousekeepingStatusIn,
    RoomBoardRow,
    RoomMoveIn,
    UndoCheckInIn,
)
from app.modules.reservations import service as reservations
from app.modules.reservations.schemas import ReservationOut

router = APIRouter(prefix="/hotels/{hotel_id}", tags=["front desk"])

View = hotel_ctx(P.RESERVATIONS_VIEW)
RoomsView = hotel_ctx(P.ROOMS_VIEW)
CheckIn = hotel_ctx(P.FRONTDESK_CHECKIN)
CheckOut = hotel_ctx(P.FRONTDESK_CHECKOUT)
Housekeeping = hotel_ctx(P.HOUSEKEEPING_UPDATE)


@router.get("/front-desk", response_model=FrontDeskOut)
async def front_desk(ctx: View, db: DB, day: date | None = None):
    return await service.front_desk(db, ctx, day)


@router.get("/room-board", response_model=list[RoomBoardRow])
async def room_board(ctx: RoomsView, db: DB):
    return await service.room_board(db, ctx)


@router.post("/reservations/{res_id}/check-in", response_model=ReservationOut)
async def check_in(res_id: uuid.UUID, body: CheckInIn, ctx: CheckIn, db: DB):
    res = await service.check_in(
        db,
        ctx,
        res_id,
        version=body.version,
        reservation_room_ids=body.reservation_room_ids,
        ignore_room_status=body.ignore_room_status,
    )
    return await reservations.reservation_out(db, res)


@router.post("/reservations/{res_id}/undo-check-in", response_model=ReservationOut)
async def undo_check_in(res_id: uuid.UUID, body: UndoCheckInIn, ctx: CheckIn, db: DB):
    res = await service.undo_check_in(
        db, ctx, res_id, version=body.version, reservation_room_id=body.reservation_room_id
    )
    return await reservations.reservation_out(db, res)


@router.post("/reservations/{res_id}/check-out", response_model=ReservationOut)
async def check_out(res_id: uuid.UUID, body: CheckOutIn, ctx: CheckOut, db: DB):
    res = await service.check_out(
        db,
        ctx,
        res_id,
        version=body.version,
        reservation_room_ids=body.reservation_room_ids,
        shorten_stay=body.shorten_stay,
        allow_open_balance=body.allow_open_balance,
    )
    return await reservations.reservation_out(db, res)


@router.post("/reservations/{res_id}/rooms/{rr_id}/room-move", response_model=ReservationOut)
async def room_move(res_id: uuid.UUID, rr_id: uuid.UUID, body: RoomMoveIn, ctx: CheckIn, db: DB):
    res = await service.move_in_house(
        db,
        ctx,
        res_id,
        rr_id,
        version=body.version,
        room_id=body.room_id,
        ignore_room_status=body.ignore_room_status,
        reason=body.reason,
    )
    return await reservations.reservation_out(db, res)


@router.post("/rooms/{room_id}/housekeeping-status")
async def housekeeping_status(room_id: uuid.UUID, body: HousekeepingStatusIn, ctx: Housekeeping, db: DB):
    room = await service.set_housekeeping_status(db, ctx, room_id, body.status)
    return {"room_id": room.id, "housekeeping_status": room.housekeeping_status, "version": room.version}
