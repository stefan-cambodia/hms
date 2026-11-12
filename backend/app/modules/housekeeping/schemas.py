from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from app.core.schemas import InputModel, OutputModel, SafeText, UpdateModel

TaskType = Literal["departure", "stayover", "deep_clean", "touch_up", "inspection"]
Priority = Literal["low", "normal", "high", "urgent"]
Reason = Annotated[SafeText, StringConstraints(min_length=1, max_length=500)]


class TaskIn(InputModel):
    room_id: uuid.UUID
    task_date: date | None = None
    task_type: TaskType = "touch_up"
    priority: Priority = "normal"
    assigned_to: uuid.UUID | None = None
    notes: Annotated[SafeText, StringConstraints(max_length=2000)] | None = None


class TaskUpdate(UpdateModel):
    priority: Priority | None = None
    assigned_to: uuid.UUID | None = None
    notes: Annotated[SafeText, StringConstraints(max_length=2000)] | None = None


class AssignIn(InputModel):
    task_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    user_id: uuid.UUID | None = None


class ActionIn(InputModel):
    reason: Reason | None = None


class TaskOut(OutputModel):
    id: uuid.UUID
    room_id: uuid.UUID
    room_number: str
    room_type_id: uuid.UUID
    task_date: date
    task_type: str
    priority: str
    status: str
    source: str
    assigned_to: uuid.UUID | None
    assigned_to_name: str | None
    reservation_room_id: uuid.UUID | None
    notes: str | None
    skip_reason: str | None
    started_at: datetime | None
    completed_at: datetime | None
    completed_by_name: str | None
    inspected_at: datetime | None
    inspected_by_name: str | None
    room_status: str
    arrival_today: bool
    version: int


class StaffOut(OutputModel):
    id: uuid.UUID
    full_name: str


class PrepareOut(OutputModel):
    created: int
    existing: int


class StatusChangeOut(OutputModel):
    at: datetime
    from_status: str
    to_status: str
    cause: str
    task_id: uuid.UUID | None
    user_name: str | None
