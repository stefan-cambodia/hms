from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from app.core.schemas import InputModel, OutputModel, SafeText, UpdateModel


class CheckInIn(UpdateModel):
    # Default: every stay arriving by today. Explicit ids check in only those.
    reservation_room_ids: list[uuid.UUID] | None = Field(None, max_length=50)
    # Check in although the room is not clean yet (the guest waits or accepts).
    ignore_room_status: bool = False


class CheckOutIn(UpdateModel):
    reservation_room_ids: list[uuid.UUID] | None = Field(None, max_length=50)
    # Confirms that a guest leaving before the planned date gives up the
    # remaining nights (they are released and removed from the bill).
    shorten_stay: bool = False
    # Leave a balance open: amount due needs folio.adjust; a credit (refund
    # owed to the guest) only needs this confirmation.
    allow_open_balance: bool = False


class UndoCheckInIn(UpdateModel):
    reservation_room_id: uuid.UUID


class RoomMoveIn(UpdateModel):
    room_id: uuid.UUID
    ignore_room_status: bool = False
    reason: Annotated[SafeText, StringConstraints(max_length=300)] | None = None


class HousekeepingStatusIn(InputModel):
    status: Literal["clean", "dirty", "in_progress", "inspected"]


class StayRow(OutputModel):
    reservation_id: uuid.UUID
    code: str
    status: str
    version: int
    reservation_room_id: uuid.UUID
    guest_id: uuid.UUID
    guest_name: str
    vip_level: int
    room_id: uuid.UUID | None
    room_number: str | None
    room_type_id: uuid.UUID
    housekeeping_status: str | None
    arrival: date
    departure: date
    adults: int
    children: int
    checked_in_at: datetime | None
    checked_out_at: datetime | None
    balance: Decimal
    currency: str
    special_requests: str | None
    # late_arrival: expected before today and not arrived; overdue: should have left.
    flags: list[str]


class FrontDeskOut(OutputModel):
    date: date
    is_today: bool
    arrivals: list[StayRow]
    departures: list[StayRow]
    in_house: list[StayRow]


class BlockInfo(OutputModel):
    id: uuid.UUID
    reason: str
    start_date: date
    end_date: date


class RoomBoardRow(OutputModel):
    room_id: uuid.UUID
    number: str
    room_type_id: uuid.UUID
    floor_id: uuid.UUID | None
    housekeeping_status: str
    version: int
    block: BlockInfo | None
    occupant: StayRow | None
    arriving: StayRow | None
    # Occupant due to leave today (or overdue).
    departing: bool
