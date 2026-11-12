"""The contract between the channel manager core and a provider adapter.

An adapter only translates messages and handles transport. Deciding *what*
to send (delta computation), retries, idempotent import and logging belong
to the core, so they behave the same for every provider.

Adapters never receive or return card numbers: when a provider message
contains payment card data, the adapter keeps only the brand and the last
four digits, and the raw message is redacted before it is logged.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol


class Capability(StrEnum):
    TEST = "test"
    MAPPING_FETCH = "mapping_fetch"
    ARI_PUSH = "ari_push"
    RES_PULL = "res_pull"


class ErrorKind(StrEnum):
    AUTH = "auth"  # credentials or account refused: stop and tell an administrator
    CONFIG = "config"  # unknown hotel/room/rate code: fix the mapping
    DATA = "data"  # the provider rejected the content (whole message rejected)
    TRANSIENT = "transient"  # network, timeout, 5xx: retry with backoff


class ChannelError(Exception):
    def __init__(self, kind: ErrorKind, message: str, *, http_status: int | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message[:500]
        self.http_status = http_status

    @property
    def retryable(self) -> bool:
        return self.kind == ErrorKind.TRANSIENT


@dataclass(frozen=True)
class ConnectionConfig:
    """Decrypted settings handed to the adapter for one call."""

    endpoint_url: str | None
    environment: str  # test | production
    account_code: str
    username: str
    password: str
    hotel_code: str
    settings: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Exchange:
    """One request/response pair, for the message log. Bodies must already be
    redacted by the adapter (see redact.py)."""

    operation: str
    outcome: str  # ok | warning | error
    http_status: int | None
    duration_ms: int
    summary: str
    request_body: str | None = None
    response_body: str | None = None


ExchangeLog = Callable[[Exchange], None]


@dataclass(frozen=True)
class TestResult:
    __test__ = False  # not a pytest test class

    ok: bool
    message: str


@dataclass(frozen=True)
class ExternalProduct:
    room_code: str
    room_name: str | None
    rate_code: str | None
    rate_name: str | None
    included_occupancy: int | None = None


# ARI updates. Dates are inclusive on both ends; consecutive nights with the
# same value are merged by the core before reaching the adapter.


@dataclass(frozen=True)
class InventoryUpdate:
    room_code: str
    start: date
    end: date
    available: int


@dataclass(frozen=True)
class RestrictionUpdate:
    """Only the restrictions that changed are set; None = leave unchanged.
    For min_stay / max_stay, 0 means "no limit" (the adapter maps it to the
    provider's own way of removing the limit)."""

    room_code: str
    rate_code: str
    start: date
    end: date
    closed: bool | None = None
    closed_to_arrival: bool | None = None
    closed_to_departure: bool | None = None
    min_stay: int | None = None
    max_stay: int | None = None


@dataclass(frozen=True)
class RateUpdate:
    room_code: str
    rate_code: str
    start: date
    end: date
    amount: Decimal
    currency: str
    after_tax: bool


# Reservations received from a channel.


@dataclass
class InboundGuest:
    first_name: str
    last_name: str
    email: str | None = None
    phone: str | None = None
    country: str | None = None  # ISO 3166-1 alpha-2 when the provider gives it


@dataclass
class InboundNight:
    night: date
    amount: Decimal
    rate_code: str | None


@dataclass
class InboundStay:
    room_code: str | None
    rate_code: str | None
    arrival: date
    departure: date
    adults: int
    children: int
    nights: list[InboundNight] = field(default_factory=list)
    total: Decimal | None = None
    comments: list[str] = field(default_factory=list)


@dataclass
class InboundBooking:
    external_id: str  # the provider's reservation id, stable across revisions
    message_id: str  # id of this revision, used to acknowledge it
    action: str  # book | modify | cancel
    message_at: datetime | None
    hotel_code: str | None
    channel_code: str | None
    channel_name: str | None
    channel_reference: str | None
    currency: str | None
    amounts_after_tax: bool
    total: Decimal | None
    stays: list[InboundStay]
    booker: InboundGuest | None
    comments: list[str] = field(default_factory=list)
    card_brand: str | None = None
    card_last4: str | None = None
    # Values with no structured place in the PMS (deposit, commission...): shown to staff.
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ConfirmItem:
    message_id: str
    external_id: str
    action: str
    ok: bool
    pms_reference: str | None
    at: datetime
    error_text: str | None = None


class ChannelAdapter(Protocol):
    provider: str
    capabilities: frozenset[Capability]

    async def test_connection(self, conn: ConnectionConfig, log: ExchangeLog) -> TestResult: ...

    async def fetch_mapping(self, conn: ConnectionConfig, log: ExchangeLog) -> list[ExternalProduct]: ...

    async def push_inventory(
        self, conn: ConnectionConfig, updates: list[InventoryUpdate], log: ExchangeLog
    ) -> None: ...

    async def push_restrictions(
        self, conn: ConnectionConfig, updates: list[RestrictionUpdate], log: ExchangeLog
    ) -> None: ...

    async def push_rates(
        self, conn: ConnectionConfig, updates: list[RateUpdate], log: ExchangeLog
    ) -> None: ...

    async def pull_bookings(self, conn: ConnectionConfig, log: ExchangeLog) -> list[InboundBooking]: ...

    async def confirm_bookings(
        self, conn: ConnectionConfig, items: list[ConfirmItem], log: ExchangeLog
    ) -> None: ...
