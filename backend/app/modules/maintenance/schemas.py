from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import StringConstraints, model_validator

from app.core.schemas import InputModel, OutputModel, SafeText, UpdateModel

Category = Literal[
    "plumbing",
    "electrical",
    "air_conditioning",
    "furniture",
    "appliance",
    "building",
    "it_network",
    "pest_control",
    "other",
]
Priority = Literal["low", "normal", "high", "urgent"]
Status = Literal["reported", "in_progress", "on_hold", "completed", "cancelled"]
Text = Annotated[SafeText, StringConstraints(max_length=5000)]


class OutOfServiceIn(InputModel):
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def _dates(self) -> OutOfServiceIn:
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        return self


class RequestIn(InputModel):
    room_id: uuid.UUID | None = None
    facility_id: uuid.UUID | None = None
    location: Annotated[SafeText, StringConstraints(max_length=200)] | None = None
    category: Category = "other"
    priority: Priority = "normal"
    title: Annotated[SafeText, StringConstraints(min_length=1, max_length=200)]
    description: Text | None = None
    assigned_to: uuid.UUID | None = None
    # Take the room out of service now (needs maintenance.manage).
    out_of_service: OutOfServiceIn | None = None

    @model_validator(mode="after")
    def _where(self) -> RequestIn:
        if not (self.room_id or self.facility_id or self.location):
            raise ValueError("a room, a facility or a location is required")
        if self.out_of_service and not self.room_id:
            raise ValueError("only a room can be taken out of service")
        return self


class RequestUpdate(UpdateModel):
    category: Category | None = None
    priority: Priority | None = None
    title: Annotated[SafeText, StringConstraints(min_length=1, max_length=200)] | None = None
    description: Text | None = None
    assigned_to: uuid.UUID | None = None


class StatusIn(UpdateModel):
    status: Status
    comment: Text | None = None
    resolution: Text | None = None
    # On completion: put the room back in service, and send housekeeping in.
    release_room: bool = True
    needs_cleaning: bool = True


class BlockIn(UpdateModel):
    start_date: date
    end_date: date


class CommentIn(InputModel):
    comment: Annotated[SafeText, StringConstraints(min_length=1, max_length=5000)]


class BlockOut(OutputModel):
    id: uuid.UUID
    start_date: date
    end_date: date


class RequestOut(OutputModel):
    id: uuid.UUID
    number: str
    room_id: uuid.UUID | None
    room_number: str | None
    facility_id: uuid.UUID | None
    location: str | None
    category: str
    priority: str
    title: str
    description: str | None
    status: str
    assigned_to: uuid.UUID | None
    assigned_to_name: str | None
    reported_by_name: str | None
    block: BlockOut | None
    started_at: datetime | None
    completed_at: datetime | None
    resolution: str | None
    created_at: datetime
    updated_at: datetime
    version: int


class UpdateOut(OutputModel):
    id: int
    at: datetime
    user_name: str | None
    action: str
    comment: str | None
    details: dict[str, Any]


class RequestDetailOut(RequestOut):
    updates: list[UpdateOut]


class TechnicianOut(OutputModel):
    id: uuid.UUID
    full_name: str
