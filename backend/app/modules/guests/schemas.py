from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import Field

from app.core.schemas import (
    CountryCode,
    InputModel,
    LanguageCode,
    Notes,
    OutputModel,
    StaffEmail,
    UpdateModel,
)

ID_DOCUMENT_TYPES = ("passport", "national_id", "driving_licence", "residence_permit", "other")


class GuestFields(InputModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: StaffEmail | None = None
    phone: str | None = Field(None, max_length=40, pattern=r"^[0-9+()\-\s\.]*$")
    nationality: CountryCode | None = None
    preferred_language: LanguageCode | None = None
    address: str | None = Field(None, max_length=300)
    city: str | None = Field(None, max_length=100)
    country_code: CountryCode | None = None
    date_of_birth: date | None = None
    vip_level: int = Field(0, ge=0, le=5)
    tags: list[str] = Field(default_factory=list, max_length=20)
    preferences: dict[str, Any] = Field(default_factory=dict)
    notes: Notes | None = None
    id_document_type: str | None = Field(
        None, pattern=r"^(passport|national_id|driving_licence|residence_permit|other)$"
    )
    id_document_number: str | None = Field(None, max_length=60)
    id_document_country: CountryCode | None = None
    id_document_expiry: date | None = None
    marketing_consent: bool = False


class GuestIn(GuestFields):
    pass


class GuestUpdate(UpdateModel):
    first_name: str | None = Field(None, min_length=1, max_length=100)
    last_name: str | None = Field(None, min_length=1, max_length=100)
    email: StaffEmail | None = None
    phone: str | None = Field(None, max_length=40, pattern=r"^[0-9+()\-\s\.]*$")
    nationality: CountryCode | None = None
    preferred_language: LanguageCode | None = None
    address: str | None = Field(None, max_length=300)
    city: str | None = Field(None, max_length=100)
    country_code: CountryCode | None = None
    date_of_birth: date | None = None
    vip_level: int | None = Field(None, ge=0, le=5)
    tags: list[str] | None = Field(None, max_length=20)
    preferences: dict[str, Any] | None = None
    notes: Notes | None = None
    id_document_type: str | None = Field(
        None, pattern=r"^(passport|national_id|driving_licence|residence_permit|other)$"
    )
    id_document_number: str | None = Field(None, max_length=60)
    id_document_country: CountryCode | None = None
    id_document_expiry: date | None = None
    marketing_consent: bool | None = None


class GuestOut(OutputModel):
    id: uuid.UUID
    first_name: str
    last_name: str
    email: str | None
    phone: str | None
    nationality: str | None
    preferred_language: str | None
    address: str | None
    city: str | None
    country_code: str | None
    vip_level: int
    tags: list[str]
    preferences: dict[str, Any]
    notes: str | None
    marketing_consent: bool
    version: int
    created_at: datetime
    # Sensitive: only filled for users holding guests.view_sensitive.
    date_of_birth: date | None = None
    id_document_type: str | None = None
    id_document_number: str | None = None
    id_document_country: str | None = None
    id_document_expiry: date | None = None
    has_id_document: bool = False


class GuestDuplicateOut(OutputModel):
    guest: GuestOut
    reasons: list[str]
    score: float
