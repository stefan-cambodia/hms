from __future__ import annotations

import re
import uuid
from decimal import Decimal
from typing import Literal

from pydantic import Field, field_validator

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

FacilityCategory = Literal[
    "pool",
    "restaurant",
    "bar",
    "rooftop",
    "spa",
    "fitness",
    "garden",
    "parking",
    "laundry",
    "transfer",
    "room_service",
    "meeting_room",
    "beach",
    "wifi",
    "breakfast",
    "massage",
    "other",
]
PricingMode = Literal["free", "paid", "on_request"]
PricingUnit = Literal["per_item", "per_night", "per_person", "per_person_night", "per_stay"]
TaxKind = Literal["percent", "fixed_per_night", "fixed_per_person_night"]
TaxScope = Literal["accommodation", "services", "all"]
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$|^24:00$")

OpeningHours = dict[str, list[tuple[str, str]]]


def _validate_hours(value: OpeningHours | None) -> OpeningHours | None:
    if value is None:
        return value
    for day, ranges in value.items():
        if day not in WEEKDAYS:
            raise ValueError(f"unknown weekday {day!r}")
        if len(ranges) > 6:
            raise ValueError("too many ranges")
        for start, end in ranges:
            if not _HHMM.match(start) or not _HHMM.match(end):
                raise ValueError("times must be HH:MM")
            # end <= start is allowed: the facility closes after midnight.
            if start == end:
                raise ValueError("empty time range")
    return value


class FacilityIn(InputModel):
    code: Code
    category: FacilityCategory = "other"
    name: RequiredLocalizedName
    description: LocalizedText = Field(default_factory=dict)
    opening_hours: OpeningHours = Field(default_factory=dict)
    is_available: bool = True
    pricing_mode: PricingMode = "free"
    price: Money | None = None
    price_unit: PricingUnit | None = None
    conditions: LocalizedText = Field(default_factory=dict)
    notes: Notes | None = None
    sort_order: int = Field(0, ge=0, le=32000)
    is_active: bool = True

    _hours = field_validator("opening_hours")(_validate_hours)


class FacilityUpdate(UpdateModel):
    code: Code | None = None
    category: FacilityCategory | None = None
    name: RequiredLocalizedName | None = None
    description: LocalizedText | None = None
    opening_hours: OpeningHours | None = None
    is_available: bool | None = None
    pricing_mode: PricingMode | None = None
    price: Money | None = None
    price_unit: PricingUnit | None = None
    conditions: LocalizedText | None = None
    notes: Notes | None = None
    sort_order: int | None = Field(None, ge=0, le=32000)
    is_active: bool | None = None

    _hours = field_validator("opening_hours")(_validate_hours)


class FacilityOut(OutputModel):
    id: uuid.UUID
    code: str
    category: str
    name: dict[str, str]
    description: dict[str, str]
    opening_hours: dict[str, list[list[str]]]
    is_available: bool
    pricing_mode: str
    price: Decimal | None
    price_unit: str | None
    conditions: dict[str, str]
    notes: str | None
    sort_order: int
    is_active: bool
    version: int


class ServiceIn(InputModel):
    code: Code
    name: RequiredLocalizedName
    description: LocalizedText = Field(default_factory=dict)
    facility_id: uuid.UUID | None = None
    price: Money
    pricing_unit: PricingUnit = "per_item"
    sort_order: int = Field(0, ge=0, le=32000)
    is_active: bool = True


class ServiceUpdate(UpdateModel):
    code: Code | None = None
    name: RequiredLocalizedName | None = None
    description: LocalizedText | None = None
    facility_id: uuid.UUID | None = None
    price: Money | None = None
    pricing_unit: PricingUnit | None = None
    sort_order: int | None = Field(None, ge=0, le=32000)
    is_active: bool | None = None


class ServiceOut(OutputModel):
    id: uuid.UUID
    code: str
    name: dict[str, str]
    description: dict[str, str]
    facility_id: uuid.UUID | None
    price: Decimal
    pricing_unit: str
    sort_order: int
    is_active: bool
    version: int


class TaxRateIn(InputModel):
    code: Code
    name: RequiredLocalizedName
    kind: TaxKind = "percent"
    rate: Decimal = Field(ge=0, max_digits=12, decimal_places=4)
    is_inclusive: bool = False
    applies_to: TaxScope = "all"
    sort_order: int = Field(0, ge=0, le=32000)
    is_active: bool = True


class TaxRateUpdate(UpdateModel):
    code: Code | None = None
    name: RequiredLocalizedName | None = None
    kind: TaxKind | None = None
    rate: Decimal | None = Field(None, ge=0, max_digits=12, decimal_places=4)
    is_inclusive: bool | None = None
    applies_to: TaxScope | None = None
    sort_order: int | None = Field(None, ge=0, le=32000)
    is_active: bool | None = None


class TaxRateOut(OutputModel):
    id: uuid.UUID
    code: str
    name: dict[str, str]
    kind: str
    rate: Decimal
    is_inclusive: bool
    applies_to: str
    sort_order: int
    is_active: bool
    version: int
