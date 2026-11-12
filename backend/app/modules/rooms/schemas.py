from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from app.core.schemas import (
    Code,
    InputModel,
    LocalizedText,
    Money,
    Notes,
    OutputModel,
    RequiredLocalizedName,
    UpdateModel,
)

BedType = Literal["single", "double", "queen", "king", "twin", "sofa_bed", "bunk", "crib"]
BathroomType = Literal["private_shower", "private_bathtub", "private_shower_bathtub", "shared"]
HEX_COLOR = r"^#[0-9a-fA-F]{6}$"
ROOM_NUMBER = r"^[A-Za-z0-9][A-Za-z0-9\-_/\. ]*$"


class BedItem(InputModel):
    type: BedType
    count: int = Field(ge=1, le=20)


class BedItemOut(OutputModel):
    type: str
    count: int


# --- Amenities ---------------------------------------------------------------


class AmenityIn(InputModel):
    code: Code
    name: RequiredLocalizedName
    icon: str | None = Field(None, max_length=40, pattern=r"^[a-z0-9\-]+$")
    scope: Literal["room", "hotel"] = "room"
    sort_order: int = Field(0, ge=0, le=32000)
    is_active: bool = True


class AmenityUpdate(UpdateModel):
    code: Code | None = None
    name: RequiredLocalizedName | None = None
    icon: str | None = Field(None, max_length=40, pattern=r"^[a-z0-9\-]+$")
    scope: Literal["room", "hotel"] | None = None
    sort_order: int | None = Field(None, ge=0, le=32000)
    is_active: bool | None = None


class AmenityOut(OutputModel):
    id: uuid.UUID
    code: str
    name: dict[str, str]
    icon: str | None
    scope: str
    sort_order: int
    is_active: bool
    version: int


# --- Room types (categories) -------------------------------------------------


def occupancy_error(
    base_occupancy: int, max_occupancy: int, max_adults: int, max_children: int
) -> str | None:
    if max_occupancy < base_occupancy:
        return "MAX_OCCUPANCY_BELOW_BASE"
    if max_adults > max_occupancy:
        return "MAX_ADULTS_ABOVE_MAX_OCCUPANCY"
    if max_children > max_occupancy:
        return "MAX_CHILDREN_ABOVE_MAX_OCCUPANCY"
    return None


class RoomTypeIn(InputModel):
    code: Code
    name: RequiredLocalizedName
    description: LocalizedText = Field(default_factory=dict)
    base_occupancy: int = Field(2, ge=1, le=50)
    max_occupancy: int = Field(2, ge=1, le=50)
    max_adults: int = Field(2, ge=1, le=50)
    max_children: int = Field(0, ge=0, le=50)
    bed_configuration: list[BedItem] = Field(default_factory=list, max_length=10)
    size_sqm: Decimal | None = Field(None, ge=0, le=10000, decimal_places=2)
    base_price: Money
    extra_adult_price: Money = Decimal("0")
    extra_child_price: Money = Decimal("0")
    color: str | None = Field(None, pattern=HEX_COLOR)
    sort_order: int = Field(0, ge=0, le=32000)
    is_active: bool = True
    amenity_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)


class RoomTypeUpdate(UpdateModel):
    code: Code | None = None
    name: RequiredLocalizedName | None = None
    description: LocalizedText | None = None
    base_occupancy: int | None = Field(None, ge=1, le=50)
    max_occupancy: int | None = Field(None, ge=1, le=50)
    max_adults: int | None = Field(None, ge=1, le=50)
    max_children: int | None = Field(None, ge=0, le=50)
    bed_configuration: list[BedItem] | None = Field(None, max_length=10)
    size_sqm: Decimal | None = Field(None, ge=0, le=10000, decimal_places=2)
    base_price: Money | None = None
    extra_adult_price: Money | None = None
    extra_child_price: Money | None = None
    color: str | None = Field(None, pattern=HEX_COLOR)
    sort_order: int | None = Field(None, ge=0, le=32000)
    is_active: bool | None = None
    amenity_ids: list[uuid.UUID] | None = Field(None, max_length=200)


class RoomTypeOut(OutputModel):
    id: uuid.UUID
    code: str
    name: dict[str, str]
    description: dict[str, str]
    base_occupancy: int
    max_occupancy: int
    max_adults: int
    max_children: int
    bed_configuration: list[BedItemOut]
    size_sqm: Decimal | None
    base_price: Decimal
    extra_adult_price: Decimal
    extra_child_price: Decimal
    color: str | None
    sort_order: int
    is_active: bool
    version: int
    amenity_ids: list[uuid.UUID] = Field(default_factory=list)
    room_count: int = 0


# --- Rooms -------------------------------------------------------------------


class RoomIn(InputModel):
    room_type_id: uuid.UUID
    building_id: uuid.UUID | None = None
    floor_id: uuid.UUID | None = None
    number: str = Field(min_length=1, max_length=20, pattern=ROOM_NUMBER)
    name: str | None = Field(None, max_length=100)
    max_occupancy: int | None = Field(None, ge=1, le=50)
    bed_configuration: list[BedItem] | None = Field(None, max_length=10)
    size_sqm: Decimal | None = Field(None, ge=0, le=10000, decimal_places=2)
    bathroom: BathroomType | None = None
    has_balcony: bool = False
    view: str | None = Field(None, max_length=60)
    base_price: Money | None = None
    notes: Notes | None = None
    sort_order: int = Field(0, ge=0, le=32000)
    is_active: bool = True
    amenity_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)


class RoomUpdate(UpdateModel):
    room_type_id: uuid.UUID | None = None
    building_id: uuid.UUID | None = None
    floor_id: uuid.UUID | None = None
    number: str | None = Field(None, min_length=1, max_length=20, pattern=ROOM_NUMBER)
    name: str | None = Field(None, max_length=100)
    max_occupancy: int | None = Field(None, ge=1, le=50)
    bed_configuration: list[BedItem] | None = Field(None, max_length=10)
    size_sqm: Decimal | None = Field(None, ge=0, le=10000, decimal_places=2)
    bathroom: BathroomType | None = None
    has_balcony: bool | None = None
    view: str | None = Field(None, max_length=60)
    base_price: Money | None = None
    notes: Notes | None = None
    sort_order: int | None = Field(None, ge=0, le=32000)
    is_active: bool | None = None
    amenity_ids: list[uuid.UUID] | None = Field(None, max_length=200)


class RoomBulkIn(InputModel):
    """Create a numbered series of rooms, e.g. prefix "" start 101 end 120."""

    room_type_id: uuid.UUID
    building_id: uuid.UUID | None = None
    floor_id: uuid.UUID | None = None
    prefix: str = Field("", max_length=10, pattern=r"^[A-Za-z0-9\-]*$")
    start: int = Field(ge=0, le=99999)
    end: int = Field(ge=0, le=99999)
    pad: int = Field(0, ge=0, le=6)
    amenity_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def _range(self) -> RoomBulkIn:
        if self.end < self.start:
            raise ValueError("end must be >= start")
        if self.end - self.start >= 500:
            raise ValueError("at most 500 rooms per batch")
        return self

    def numbers(self) -> list[str]:
        return [f"{self.prefix}{str(n).zfill(self.pad)}" for n in range(self.start, self.end + 1)]


class RoomOut(OutputModel):
    id: uuid.UUID
    room_type_id: uuid.UUID
    building_id: uuid.UUID | None
    floor_id: uuid.UUID | None
    number: str
    name: str | None
    max_occupancy: int | None
    bed_configuration: list[BedItemOut] | None
    size_sqm: Decimal | None
    bathroom: str | None
    has_balcony: bool
    view: str | None
    base_price: Decimal | None
    housekeeping_status: str
    notes: str | None
    sort_order: int
    is_active: bool
    version: int
    amenity_ids: list[uuid.UUID] = Field(default_factory=list)
