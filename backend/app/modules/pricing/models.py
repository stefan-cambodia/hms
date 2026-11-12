"""Rate plans, the daily rate/restriction grid, pricing rules and
cancellation policies."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, Timestamps, UUIDPk, Versioned

MEAL_PLANS = ("room_only", "breakfast", "half_board", "full_board", "all_inclusive")
DERIVE_MODES = ("percent", "amount", "amount_per_person")
RULE_KINDS = ("season", "weekday", "occupancy", "long_stay", "last_minute", "early_bird")
# Rules that shape the computed nightly rate (ignored when an explicit daily price exists).
RATE_RULE_KINDS = ("season", "weekday", "occupancy")
# Discounts that apply on top of any price, depending on the booking.
DISCOUNT_RULE_KINDS = ("long_stay", "last_minute", "early_bird")
ADJUSTMENTS = ("percent", "amount", "set")


class CancellationPolicy(UUIDPk, Timestamps, Versioned, Base):
    __tablename__ = "cancellation_policies"

    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[dict[str, str]] = mapped_column(JSONB)
    description: Mapped[dict[str, str]] = mapped_column(JSONB, server_default=text("'{}'"))
    # Free cancellation until N days before arrival (None = never free).
    free_until_days: Mapped[int | None] = mapped_column(SmallInteger)
    # Penalty after the free period: percentage of the stay, or a number of nights.
    penalty_kind: Mapped[str] = mapped_column(String(20), server_default="nights")
    penalty_value: Mapped[Decimal] = mapped_column(Numeric(7, 2), server_default="1")
    no_show_nights: Mapped[int] = mapped_column(SmallInteger, server_default="1")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))

    __table_args__ = (
        UniqueConstraint("hotel_id", "code"),
        UniqueConstraint("hotel_id", "id"),
        CheckConstraint("penalty_kind IN ('percent','nights')", name="penalty_kind"),
        CheckConstraint("penalty_value >= 0", name="penalty_value"),
        CheckConstraint("free_until_days IS NULL OR free_until_days >= 0", name="free_until"),
    )


class RatePlan(UUIDPk, Timestamps, Versioned, Base):
    __tablename__ = "rate_plans"

    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[dict[str, str]] = mapped_column(JSONB)
    description: Mapped[dict[str, str]] = mapped_column(JSONB, server_default=text("'{}'"))
    meal_plan: Mapped[str] = mapped_column(String(20), server_default="room_only")
    is_refundable: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    cancellation_policy_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    parent_rate_plan_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    derive_mode: Mapped[str | None] = mapped_column(String(20))
    derive_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    # Empty = all room categories.
    room_type_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), server_default=text("'{}'")
    )
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    min_advance_days: Mapped[int | None] = mapped_column(SmallInteger)
    max_advance_days: Mapped[int | None] = mapped_column(SmallInteger)
    is_default: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    sort_order: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))

    __table_args__ = (
        UniqueConstraint("hotel_id", "code"),
        UniqueConstraint("hotel_id", "id"),
        ForeignKeyConstraint(
            ["hotel_id", "cancellation_policy_id"],
            ["cancellation_policies.hotel_id", "cancellation_policies.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["hotel_id", "parent_rate_plan_id"],
            ["rate_plans.hotel_id", "rate_plans.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "meal_plan IN ('room_only','breakfast','half_board','full_board','all_inclusive')",
            name="meal_plan",
        ),
        CheckConstraint(
            "(parent_rate_plan_id IS NULL AND derive_mode IS NULL)"
            " OR (parent_rate_plan_id IS NOT NULL AND derive_mode IN ('percent','amount','amount_per_person')"
            " AND derive_value IS NOT NULL)",
            name="derivation",
        ),
        CheckConstraint("parent_rate_plan_id IS NULL OR parent_rate_plan_id <> id", name="not_self"),
        CheckConstraint("valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from", name="validity"),
        # Exactly one default plan per hotel (the one used when none is chosen).
        Index("uq_rate_plans_default", "hotel_id", unique=True, postgresql_where=text("is_default")),
    )


class DailyRate(Base):
    """One cell of the rate grid: explicit price and restrictions for a plan,
    a room category and a date. Missing rows mean "computed, unrestricted"."""

    __tablename__ = "daily_rates"

    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"))
    rate_plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rate_plans.id", ondelete="CASCADE"))
    room_type_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("room_types.id", ondelete="CASCADE"))
    date: Mapped[date] = mapped_column(Date)
    price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    min_stay: Mapped[int | None] = mapped_column(SmallInteger)
    max_stay: Mapped[int | None] = mapped_column(SmallInteger)
    closed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    closed_to_arrival: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    closed_to_departure: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))

    __table_args__ = (
        PrimaryKeyConstraint("rate_plan_id", "room_type_id", "date"),
        Index("ix_daily_rates_hotel_date", "hotel_id", "date"),
        CheckConstraint("price IS NULL OR price >= 0", name="price"),
        CheckConstraint("min_stay IS NULL OR min_stay >= 1", name="min_stay"),
        CheckConstraint(
            "max_stay IS NULL OR (max_stay >= 1 AND (min_stay IS NULL OR max_stay >= min_stay))",
            name="max_stay",
        ),
    )


class PricingRule(UUIDPk, Timestamps, Versioned, Base):
    __tablename__ = "pricing_rules"

    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"))
    name: Mapped[dict[str, str]] = mapped_column(JSONB)
    kind: Mapped[str] = mapped_column(String(20))
    priority: Mapped[int] = mapped_column(SmallInteger, server_default="100")
    date_from: Mapped[date | None] = mapped_column(Date)
    date_to: Mapped[date | None] = mapped_column(Date)
    weekdays: Mapped[list[int]] = mapped_column(ARRAY(SmallInteger), server_default=text("'{}'"))
    room_type_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), server_default=text("'{}'")
    )
    rate_plan_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), server_default=text("'{}'")
    )
    adjustment: Mapped[str] = mapped_column(String(10))
    value: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    # {"min_nights": 7} | {"max_days_before": 3} | {"min_days_before": 60} | {"min_occupancy": 80}
    conditions: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))

    __table_args__ = (
        CheckConstraint(
            "kind IN ('season','weekday','occupancy','long_stay','last_minute','early_bird')", name="kind"
        ),
        CheckConstraint("adjustment IN ('percent','amount','set')", name="adjustment"),
        CheckConstraint("date_to IS NULL OR date_from IS NULL OR date_to >= date_from", name="dates"),
        CheckConstraint("adjustment <> 'set' OR value >= 0", name="set_positive"),
        Index("ix_pricing_rules_hotel", "hotel_id", "is_active"),
    )
