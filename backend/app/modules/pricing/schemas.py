from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field, model_validator

from app.core.schemas import (
    Code,
    InputModel,
    LocalizedText,
    OutputModel,
    RequiredLocalizedName,
    UpdateModel,
)

MealPlan = Literal["room_only", "breakfast", "half_board", "full_board", "all_inclusive"]
DeriveMode = Literal["percent", "amount", "amount_per_person"]
RuleKind = Literal["season", "weekday", "occupancy", "long_stay", "last_minute", "early_bird"]
Adjustment = Literal["percent", "amount", "set"]
Weekday = Literal[0, 1, 2, 3, 4, 5, 6]


# --- rate plans ------------------------------------------------------------------


class RatePlanIn(InputModel):
    code: Code
    name: RequiredLocalizedName
    description: LocalizedText = Field(default_factory=dict)
    meal_plan: MealPlan = "room_only"
    is_refundable: bool = True
    cancellation_policy_id: uuid.UUID | None = None
    parent_rate_plan_id: uuid.UUID | None = None
    derive_mode: DeriveMode | None = None
    derive_value: Decimal | None = Field(None, ge=-1_000_000, le=1_000_000, decimal_places=2)
    room_type_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)
    valid_from: date | None = None
    valid_to: date | None = None
    min_advance_days: int | None = Field(None, ge=0, le=1000)
    max_advance_days: int | None = Field(None, ge=0, le=1000)
    is_default: bool = False
    sort_order: int = Field(0, ge=0, le=32000)
    is_active: bool = True


class RatePlanUpdate(UpdateModel):
    code: Code | None = None
    name: RequiredLocalizedName | None = None
    description: LocalizedText | None = None
    meal_plan: MealPlan | None = None
    is_refundable: bool | None = None
    cancellation_policy_id: uuid.UUID | None = None
    parent_rate_plan_id: uuid.UUID | None = None
    derive_mode: DeriveMode | None = None
    derive_value: Decimal | None = Field(None, ge=-1_000_000, le=1_000_000, decimal_places=2)
    room_type_ids: list[uuid.UUID] | None = Field(None, max_length=200)
    valid_from: date | None = None
    valid_to: date | None = None
    min_advance_days: int | None = Field(None, ge=0, le=1000)
    max_advance_days: int | None = Field(None, ge=0, le=1000)
    is_default: bool | None = None
    sort_order: int | None = Field(None, ge=0, le=32000)
    is_active: bool | None = None


class RatePlanOut(OutputModel):
    id: uuid.UUID
    code: str
    name: dict[str, str]
    description: dict[str, str]
    meal_plan: str
    is_refundable: bool
    cancellation_policy_id: uuid.UUID | None
    parent_rate_plan_id: uuid.UUID | None
    derive_mode: str | None
    derive_value: Decimal | None
    room_type_ids: list[uuid.UUID]
    valid_from: date | None
    valid_to: date | None
    min_advance_days: int | None
    max_advance_days: int | None
    is_default: bool
    sort_order: int
    is_active: bool
    version: int


# --- pricing rules ---------------------------------------------------------------


class RuleConditions(InputModel):
    min_nights: int | None = Field(None, ge=1, le=365)
    max_days_before: int | None = Field(None, ge=0, le=365)
    min_days_before: int | None = Field(None, ge=0, le=730)
    min_occupancy: int | None = Field(None, ge=0, le=100)


class _RuleBase(InputModel):
    @model_validator(mode="after")
    def _dates(self):  # type: ignore[no-untyped-def]
        df, dt = getattr(self, "date_from", None), getattr(self, "date_to", None)
        if df and dt and dt < df:
            raise ValueError("date_to must be on or after date_from")
        return self


class PricingRuleIn(_RuleBase):
    name: RequiredLocalizedName
    kind: RuleKind
    priority: int = Field(100, ge=0, le=10000)
    date_from: date | None = None
    date_to: date | None = None
    weekdays: list[Weekday] = Field(default_factory=list, max_length=7)
    room_type_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)
    rate_plan_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)
    adjustment: Adjustment
    value: Decimal = Field(ge=-1_000_000, le=1_000_000, decimal_places=2)
    conditions: RuleConditions = Field(default_factory=RuleConditions)
    is_active: bool = True

    def model_dump(self, **kw: Any) -> dict[str, Any]:  # conditions stored without empty keys
        out = super().model_dump(**kw)
        if isinstance(out.get("conditions"), dict):
            out["conditions"] = {k: v for k, v in out["conditions"].items() if v is not None}
        return out


class PricingRuleUpdate(UpdateModel):
    name: RequiredLocalizedName | None = None
    priority: int | None = Field(None, ge=0, le=10000)
    date_from: date | None = None
    date_to: date | None = None
    weekdays: list[Weekday] | None = Field(None, max_length=7)
    room_type_ids: list[uuid.UUID] | None = Field(None, max_length=200)
    rate_plan_ids: list[uuid.UUID] | None = Field(None, max_length=200)
    adjustment: Adjustment | None = None
    value: Decimal | None = Field(None, ge=-1_000_000, le=1_000_000, decimal_places=2)
    conditions: RuleConditions | None = None
    is_active: bool | None = None

    def model_dump(self, **kw: Any) -> dict[str, Any]:
        out = super().model_dump(**kw)
        if isinstance(out.get("conditions"), dict):
            out["conditions"] = {k: v for k, v in out["conditions"].items() if v is not None}
        return out


class PricingRuleOut(OutputModel):
    id: uuid.UUID
    name: dict[str, str]
    kind: str
    priority: int
    date_from: date | None
    date_to: date | None
    weekdays: list[int]
    room_type_ids: list[uuid.UUID]
    rate_plan_ids: list[uuid.UUID]
    adjustment: str
    value: Decimal
    conditions: dict[str, Any]
    is_active: bool
    version: int


# --- cancellation policies ---------------------------------------------------------


class PolicyIn(InputModel):
    code: Code
    name: RequiredLocalizedName
    description: LocalizedText = Field(default_factory=dict)
    free_until_days: int | None = Field(None, ge=0, le=365)
    penalty_kind: Literal["percent", "nights"] = "nights"
    penalty_value: Decimal = Field(Decimal("1"), ge=0, le=100000, decimal_places=2)
    no_show_nights: int = Field(1, ge=0, le=365)
    is_active: bool = True


class PolicyUpdate(UpdateModel):
    code: Code | None = None
    name: RequiredLocalizedName | None = None
    description: LocalizedText | None = None
    free_until_days: int | None = Field(None, ge=0, le=365)
    penalty_kind: Literal["percent", "nights"] | None = None
    penalty_value: Decimal | None = Field(None, ge=0, le=100000, decimal_places=2)
    no_show_nights: int | None = Field(None, ge=0, le=365)
    is_active: bool | None = None


class PolicyOut(OutputModel):
    id: uuid.UUID
    code: str
    name: dict[str, str]
    description: dict[str, str]
    free_until_days: int | None
    penalty_kind: str
    penalty_value: Decimal
    no_show_nights: int
    is_active: bool
    version: int


# --- grid, bulk edit, offers -------------------------------------------------------


class GridCell(OutputModel):
    room_type_id: uuid.UUID
    date: date
    price: Decimal
    source: str
    explicit: bool
    min_stay: int | None
    max_stay: int | None
    closed: bool
    closed_to_arrival: bool
    closed_to_departure: bool
    restrictions_inherited: bool
    available: int


class GridOut(OutputModel):
    rate_plan_id: uuid.UUID
    start: date
    end: date
    room_type_ids: list[uuid.UUID]
    cells: list[GridCell]


class PriceAction(InputModel):
    mode: Literal["set", "percent", "amount", "clear"]
    value: Decimal | None = Field(None, ge=-1_000_000, le=1_000_000, decimal_places=2)

    @model_validator(mode="after")
    def _value(self) -> PriceAction:
        if self.mode != "clear" and self.value is None:
            raise ValueError("value is required")
        if self.mode == "set" and self.value is not None and self.value < 0:
            raise ValueError("price cannot be negative")
        if self.mode == "percent" and self.value is not None and self.value <= -100:
            raise ValueError("cannot reduce by 100% or more")
        return self


class RestrictionsPatch(InputModel):
    """Only the fields sent are changed; null clears min/max stay."""

    min_stay: int | None = Field(None, ge=1, le=365)
    max_stay: int | None = Field(None, ge=1, le=365)
    closed: bool | None = None
    closed_to_arrival: bool | None = None
    closed_to_departure: bool | None = None


class BulkRatesIn(InputModel):
    rate_plan_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)
    room_type_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    start: date
    end: date  # inclusive
    weekdays: list[Weekday] = Field(default_factory=list, max_length=7)
    price: PriceAction | None = None
    restrictions: RestrictionsPatch | None = None

    @model_validator(mode="after")
    def _check(self) -> BulkRatesIn:
        if self.end < self.start:
            raise ValueError("end must be on or after start")
        if (self.end - self.start).days > 730:
            raise ValueError("at most two years at a time")
        if self.price is None and (self.restrictions is None or not self.restrictions.model_fields_set):
            raise ValueError("nothing to change")
        return self


class BulkResultOut(OutputModel):
    cells_changed: int


class OfferNight(OutputModel):
    night: date
    price: Decimal
    price_source: str


class OfferOut(OutputModel):
    room_type_id: uuid.UUID
    rate_plan_id: uuid.UUID
    total: Decimal
    average_night: Decimal
    nights: list[OfferNight]
    available: int
    issues: list[dict[str, Any]]
    bookable: bool
