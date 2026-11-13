from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from app.core.schemas import InputModel, OutputModel

OwnerType = Literal["hotel", "room_type", "facility", "maintenance_request"]


class MediaOut(OutputModel):
    id: uuid.UUID
    owner_type: OwnerType
    owner_id: uuid.UUID
    kind: Literal["logo", "photo"]
    filename: str
    content_type: str
    size: int
    width: int
    height: int
    sort_order: int
    uploaded_by: uuid.UUID | None
    uploaded_by_name: str | None
    created_at: datetime
    url: str
    thumbnail_url: str


class MediaOrderIn(InputModel):
    owner_type: OwnerType
    owner_id: uuid.UUID | None = None
    ids: list[uuid.UUID] = Field(max_length=50)
