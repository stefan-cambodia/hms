from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints, field_validator

from app.core.schemas import InputModel, OutputModel, UpdateModel

Code = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
# Provider rules: ASCII only, no < > & " ' (SiteMinder integration requirements).
Credential = Annotated[str, StringConstraints(min_length=1, max_length=200, pattern=r"^[\x21-\x7e]+$")]


def _no_xml_specials(value: str | None) -> str | None:
    if value is not None and any(ch in value for ch in "<>&\"'"):
        raise ValueError("must not contain < > & \" or '")
    return value


class ConnectionSettings(InputModel):
    rate_amount: Literal["after_tax", "before_tax"] = "after_tax"
    rest_base_url: Annotated[str, StringConstraints(max_length=300, pattern=r"^https://")] | None = None


class ConnectionIn(InputModel):
    provider: Literal["siteminder"]
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    environment: Literal["test", "production"] = "test"
    endpoint_url: Annotated[str, StringConstraints(max_length=300, pattern=r"^https://")] | None = None
    account_code: Code
    username: Credential
    password: Credential
    hotel_code: Code
    push_ari: bool = True
    pull_reservations: bool = False
    horizon_days: int = Field(365, ge=30, le=750)
    # SiteMinder: pull every 2 to 5 minutes.
    pull_interval_seconds: int = Field(180, ge=120, le=300)
    settings: ConnectionSettings = ConnectionSettings()

    _xml = field_validator("username", "password")(_no_xml_specials)


class ConnectionUpdate(UpdateModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)] | None = None
    environment: Literal["test", "production"] | None = None
    endpoint_url: Annotated[str, StringConstraints(max_length=300, pattern=r"^https://")] | None = None
    account_code: Code | None = None
    username: Credential | None = None
    password: Credential | None = None  # write-only; omitted = unchanged
    hotel_code: Code | None = None
    enabled: bool | None = None
    push_ari: bool | None = None
    pull_reservations: bool | None = None
    horizon_days: int | None = Field(None, ge=30, le=750)
    pull_interval_seconds: int | None = Field(None, ge=120, le=300)
    settings: ConnectionSettings | None = None

    _xml = field_validator("username", "password")(_no_xml_specials)


class StatusOut(OutputModel):
    state: str
    last_test_at: datetime | None
    last_test_ok: bool | None
    last_test_message: str | None
    last_push_at: datetime | None
    last_pull_at: datetime | None
    last_error_at: datetime | None
    last_error: str | None
    consecutive_failures: int
    next_push_at: datetime | None
    next_pull_at: datetime | None
    horizon_end: date | None
    full_refresh_requested: bool
    last_full_refresh_at: datetime | None
    products_fetched_at: datetime | None


class ConnectionOut(OutputModel):
    id: uuid.UUID
    provider: str
    name: str
    environment: str
    endpoint_url: str | None
    account_code: str
    username: str
    hotel_code: str
    enabled: bool
    push_ari: bool
    pull_reservations: bool
    horizon_days: int
    pull_interval_seconds: int
    settings: dict[str, Any]
    version: int
    created_at: datetime
    status: StatusOut
    pending_changes: int = 0
    unmapped_room_types: int = 0
    mapped_rates: int = 0
    bookings_attention: int = 0
    errors_24h: int = 0


class TestOut(OutputModel):
    ok: bool
    message: str
    state: str


class ProductOut(OutputModel):
    room_code: str
    room_name: str | None
    rate_code: str | None
    rate_name: str | None
    included_occupancy: int | None = None


class RoomMapIn(InputModel):
    room_type_id: uuid.UUID
    external_code: Code


class RateMapIn(InputModel):
    room_type_id: uuid.UUID
    rate_plan_id: uuid.UUID
    external_code: Code


class MappingsIn(InputModel):
    rooms: list[RoomMapIn] = Field(default_factory=list, max_length=200)
    rates: list[RateMapIn] = Field(default_factory=list, max_length=2000)


class MappingsOut(OutputModel):
    rooms: list[RoomMapIn]
    rates: list[RateMapIn]
    products: list[ProductOut]
    products_fetched_at: datetime | None
    # Codes used in the mapping that the provider did not list at the last fetch.
    unknown_codes: list[str]


class MessageOut(OutputModel):
    id: int
    at: datetime
    operation: str
    outcome: str
    http_status: int | None
    duration_ms: int | None
    summary: str | None


class MessageDetailOut(MessageOut):
    request_body: str | None
    response_body: str | None


class BookingOut(OutputModel):
    id: uuid.UUID
    connection_id: uuid.UUID
    connection_name: str
    external_id: str
    revision: str
    action: str
    channel_name: str | None
    message_at: datetime | None
    received_at: datetime
    import_status: str
    error_code: str | None
    error_detail: str | None
    reservation_id: uuid.UUID | None
    reservation_code: str | None
    overbooked: bool
    attempts: int
    confirmed_at: datetime | None
    card_brand: str | None
    card_last4: str | None
    guest_name: str | None
    arrival: date | None
    departure: date | None
    total: str | None
    currency: str | None


class DismissIn(InputModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
