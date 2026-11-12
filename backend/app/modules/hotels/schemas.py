from __future__ import annotations

import uuid
from datetime import datetime, time
from decimal import Decimal
from typing import Any

from pydantic import EmailStr, Field, HttpUrl

from app.core.schemas import (
    Code,
    CountryCode,
    CurrencyCode,
    InputModel,
    LanguageCode,
    LocalizedText,
    NonEmptyShortStr,
    OutputModel,
    ShortStr,
    UpdateModel,
)


class Policies(InputModel):
    cancellation: LocalizedText = Field(default_factory=dict)
    payment: LocalizedText = Field(default_factory=dict)
    house_rules: LocalizedText = Field(default_factory=dict)


class BillingInfo(InputModel):
    legal_address: str | None = Field(None, max_length=500)
    bank_details: str | None = Field(None, max_length=1000)
    invoice_footer: LocalizedText = Field(default_factory=dict)
    invoice_prefix: str | None = Field(None, max_length=20, pattern=r"^[A-Za-z0-9\-/]*$")
    receipt_prefix: str | None = Field(None, max_length=20, pattern=r"^[A-Za-z0-9\-/]*$")


SOCIAL_KEYS = (
    "facebook",
    "instagram",
    "tiktok",
    "x",
    "youtube",
    "tripadvisor",
    "linkedin",
    "wechat",
    "telegram",
    "line",
    "whatsapp",
)


class HotelOut(OutputModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    code: str
    name: str
    legal_name: str | None
    description: dict[str, str]
    address_line1: str | None
    address_line2: str | None
    city: str | None
    region: str | None
    postal_code: str | None
    country_code: str | None
    latitude: Decimal | None
    longitude: Decimal | None
    phone: str | None
    email: str | None
    website: str | None
    social_links: dict[str, str]
    timezone: str
    default_language: str
    supported_languages: list[str]
    currency_code: str
    check_in_time: time
    check_out_time: time
    tax_id: str | None
    billing_info: dict[str, Any]
    policies: dict[str, Any]
    is_active: bool
    version: int
    updated_at: datetime


class HotelCreate(InputModel):
    code: Code
    name: NonEmptyShortStr
    timezone: str = "UTC"
    currency_code: CurrencyCode = "USD"
    default_language: LanguageCode = "en"
    country_code: CountryCode | None = None


class HotelUpdate(UpdateModel):
    name: NonEmptyShortStr | None = None
    legal_name: ShortStr | None = None
    description: LocalizedText | None = None
    address_line1: ShortStr | None = None
    address_line2: ShortStr | None = None
    city: str | None = Field(None, max_length=100)
    region: str | None = Field(None, max_length=100)
    postal_code: str | None = Field(None, max_length=20)
    country_code: CountryCode | None = None
    latitude: Decimal | None = Field(None, ge=-90, le=90, decimal_places=6)
    longitude: Decimal | None = Field(None, ge=-180, le=180, decimal_places=6)
    phone: str | None = Field(None, max_length=40)
    email: EmailStr | None = None
    website: HttpUrl | None = None
    social_links: dict[str, str] | None = None
    timezone: str | None = Field(None, max_length=64)
    default_language: LanguageCode | None = None
    supported_languages: list[LanguageCode] | None = Field(None, min_length=1)
    currency_code: CurrencyCode | None = None
    check_in_time: time | None = None
    check_out_time: time | None = None
    tax_id: str | None = Field(None, max_length=60)
    billing_info: BillingInfo | None = None
    policies: Policies | None = None


class BuildingIn(InputModel):
    code: Code
    name: NonEmptyShortStr
    sort_order: int = Field(0, ge=0, le=32000)
    is_active: bool = True


class BuildingUpdate(UpdateModel):
    code: Code | None = None
    name: NonEmptyShortStr | None = None
    sort_order: int | None = Field(None, ge=0, le=32000)
    is_active: bool | None = None


class BuildingOut(OutputModel):
    id: uuid.UUID
    code: str
    name: str
    sort_order: int
    is_active: bool
    version: int


class FloorIn(InputModel):
    building_id: uuid.UUID
    level: int = Field(ge=-10, le=300)
    name: str = Field(min_length=1, max_length=100)
    sort_order: int = Field(0, ge=0, le=32000)


class FloorUpdate(UpdateModel):
    level: int | None = Field(None, ge=-10, le=300)
    name: str | None = Field(None, min_length=1, max_length=100)
    sort_order: int | None = Field(None, ge=0, le=32000)


class FloorOut(OutputModel):
    id: uuid.UUID
    building_id: uuid.UUID
    level: int
    name: str
    sort_order: int
    version: int
