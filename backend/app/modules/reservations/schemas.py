from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field, model_validator

from app.core.schemas import InputModel, Notes, OutputModel, UpdateModel
from app.modules.guests.schemas import GuestIn

Source = Literal["direct", "website", "booking_com", "agoda", "walk_in", "phone", "email", "other"]
Status = Literal["pending", "confirmed", "checked_in", "checked_out", "cancelled", "no_show"]
MAX_NIGHTS = 365


class StayIn(InputModel):
    room_type_id: uuid.UUID
    room_id: uuid.UUID | None = None
    arrival: date | None = None  # defaults to the reservation's dates
    departure: date | None = None
    adults: int = Field(1, ge=1, le=50)
    children: int = Field(0, ge=0, le=50)


def _check_dates(arrival: date, departure: date) -> None:
    if departure <= arrival:
        raise ValueError("departure must be after arrival")
    if (departure - arrival).days > MAX_NIGHTS:
        raise ValueError(f"a stay cannot exceed {MAX_NIGHTS} nights")


class QuoteIn(InputModel):
    arrival: date
    departure: date
    rooms: list[StayIn] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def _dates(self) -> QuoteIn:
        _check_dates(self.arrival, self.departure)
        for s in self.rooms:
            _check_dates(s.arrival or self.arrival, s.departure or self.departure)
        return self


class ReservationIn(QuoteIn):
    guest_id: uuid.UUID | None = None
    guest: GuestIn | None = None
    status: Literal["pending", "confirmed"] = "confirmed"
    source: Source = "direct"
    external_ref: str | None = Field(None, max_length=100)
    special_requests: Notes | None = None
    internal_notes: Notes | None = None
    allow_overbooking: bool = False

    @model_validator(mode="after")
    def _guest(self) -> ReservationIn:
        if (self.guest_id is None) == (self.guest is None):
            raise ValueError("provide exactly one of guest_id or guest")
        return self


class ReservationUpdate(UpdateModel):
    source: Source | None = None
    external_ref: str | None = Field(None, max_length=100)
    special_requests: Notes | None = None
    internal_notes: Notes | None = None


class AssignRoomIn(UpdateModel):
    room_id: uuid.UUID | None


class ChangeDatesIn(UpdateModel):
    arrival: date
    departure: date

    @model_validator(mode="after")
    def _dates(self) -> ChangeDatesIn:
        _check_dates(self.arrival, self.departure)
        return self


class MoveStayIn(UpdateModel):
    """Calendar drag-and-drop: target room (or null to unassign) and dates."""

    room_id: uuid.UUID | None
    arrival: date
    departure: date

    @model_validator(mode="after")
    def _dates(self) -> MoveStayIn:
        _check_dates(self.arrival, self.departure)
        return self


class CancelIn(UpdateModel):
    reason: str = Field(min_length=1, max_length=500)


class VersionIn(UpdateModel):
    pass


class NightOut(OutputModel):
    night: date
    price: Decimal
    price_source: str


class ReservationRoomOut(OutputModel):
    id: uuid.UUID
    room_type_id: uuid.UUID
    room_id: uuid.UUID | None
    arrival: date
    departure: date
    adults: int
    children: int
    occupies_inventory: bool
    accommodation_total: Decimal
    checked_in_at: datetime | None
    checked_out_at: datetime | None
    nights: list[NightOut]


class BookerOut(OutputModel):
    id: uuid.UUID
    first_name: str
    last_name: str
    email: str | None
    phone: str | None
    nationality: str | None
    vip_level: int


class TaxLineOut(OutputModel):
    code: str
    name: dict[str, str]
    kind: str
    rate: Decimal
    is_inclusive: bool
    amount: Decimal


class ReservationOut(OutputModel):
    id: uuid.UUID
    code: str
    status: str
    source: str
    external_ref: str | None
    arrival: date
    departure: date
    adults: int
    children: int
    currency: str
    accommodation_total: Decimal
    tax_total: Decimal
    grand_total: Decimal
    paid_total: Decimal
    balance: Decimal
    tax_breakdown: list[dict[str, Any]]
    is_overbooked: bool
    is_modified: bool
    special_requests: str | None
    internal_notes: str | None
    cancelled_at: datetime | None
    cancellation_reason: str | None
    booker: BookerOut
    rooms: list[ReservationRoomOut]
    version: int
    created_at: datetime
    updated_at: datetime


class ReservationListItem(OutputModel):
    id: uuid.UUID
    code: str
    status: str
    source: str
    arrival: date
    departure: date
    adults: int
    children: int
    guest_name: str
    room_numbers: list[str]
    room_count: int
    grand_total: Decimal
    balance: Decimal
    currency: str
    is_overbooked: bool


class ReservationEventOut(OutputModel):
    id: int
    at: datetime
    user_id: uuid.UUID | None
    user_name: str | None = None
    source: str
    action: str
    details: dict[str, Any]


class QuoteOut(OutputModel):
    currency: str
    accommodation_total: Decimal
    tax_total: Decimal
    grand_total: Decimal
    taxes: list[TaxLineOut]
    rooms: list[list[NightOut]]


class AvailabilityNightOut(OutputModel):
    night: date
    total: int
    available: int


class AvailabilityOut(OutputModel):
    room_type_id: uuid.UUID
    nights: list[AvailabilityNightOut]


class RoomBlockIn(InputModel):
    room_id: uuid.UUID
    start_date: date
    end_date: date
    reason: Literal["maintenance", "out_of_service", "owner_use", "other"] = "maintenance"
    notes: Notes | None = None

    @model_validator(mode="after")
    def _dates(self) -> RoomBlockIn:
        _check_dates(self.start_date, self.end_date)
        return self


class AvailableRoomOut(OutputModel):
    id: uuid.UUID
    number: str
    name: str | None
    room_type_id: uuid.UUID
    max_occupancy: int | None


class RoomBlockOut(OutputModel):
    id: uuid.UUID
    room_id: uuid.UUID
    start_date: date
    end_date: date
    reason: str
    notes: str | None


class CalendarItem(OutputModel):
    kind: Literal["stay", "block"]
    id: uuid.UUID
    room_id: uuid.UUID | None
    room_type_id: uuid.UUID | None = None
    start: date
    end: date
    reservation_id: uuid.UUID | None = None
    code: str | None = None
    guest_name: str | None = None
    status: str | None = None
    adults: int | None = None
    children: int | None = None
    block_reason: str | None = None


class CalendarOut(OutputModel):
    start: date
    end: date
    items: list[CalendarItem]
    unassigned: list[CalendarItem]
    availability: list[AvailabilityOut]
