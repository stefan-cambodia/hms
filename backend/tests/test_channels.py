"""Phase 7 — channel manager.

The core (change queue, delta computation, retries, idempotent import) is
tested with an in-memory adapter that exists only in this file and can never
be selected in the product. The SiteMinder adapter is tested against
SiteMinder's own published sample messages (tests/fixtures/siteminder), and
end to end through its HTTP transport with a recorded-style exchange.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import func, select

from app.core.db import owner_sessionmaker
from app.modules.channels import adapters as registry
from app.modules.channels.adapters.base import (
    Capability,
    ChannelError,
    ConfirmItem,
    ConnectionConfig,
    ErrorKind,
    Exchange,
    ExternalProduct,
    InboundBooking,
    InboundGuest,
    InboundNight,
    InboundStay,
    InventoryUpdate,
    RateUpdate,
    RestrictionUpdate,
    TestResult,
)
from app.modules.channels.adapters.siteminder import SiteMinderAdapter, parse_reservations
from app.modules.channels.models import ChannelBooking, ChannelDirtyRange, ChannelMessage, ChannelSyncStatus
from app.modules.channels.worker import run_once
from tests.conftest import Api, error_code

FIXTURES = Path(__file__).parent / "fixtures" / "siteminder"
TZ = ZoneInfo("Asia/Phnom_Penh")


def today() -> date:
    return datetime.now(TZ).date()


def d(offset: int) -> date:
    return today() + timedelta(days=offset)


class FakeAdapter:
    """In-memory provider for the core tests (test suite only)."""

    provider = "siteminder"
    capabilities = frozenset(Capability)

    def __init__(self) -> None:
        self.inventory: list[InventoryUpdate] = []
        self.restrictions: list[RestrictionUpdate] = []
        self.rates: list[RateUpdate] = []
        self.queue: list[InboundBooking] = []
        self.confirmed: list[ConfirmItem] = []
        self.fail: ChannelError | None = None

    def reset(self) -> None:
        self.inventory, self.restrictions, self.rates = [], [], []

    def _log(self, log, op: str, n: int) -> None:  # type: ignore[no-untyped-def]
        log(Exchange(op, "ok", 200, 1, f"{n} update(s)", "<request/>", "<response/>"))

    async def test_connection(self, conn, log):  # type: ignore[no-untyped-def]
        return TestResult(True, "fake ok")

    async def fetch_mapping(self, conn, log):  # type: ignore[no-untyped-def]
        return [ExternalProduct("STD", "Standard", "BAR", "Best available")]

    async def push_inventory(self, conn, updates, log):  # type: ignore[no-untyped-def]
        if self.fail:
            log(Exchange("avail", "error", 503, 1, self.fail.message))
            raise self.fail
        self.inventory += updates
        self._log(log, "avail", len(updates))

    async def push_restrictions(self, conn, updates, log):  # type: ignore[no-untyped-def]
        self.restrictions += updates
        self._log(log, "restrictions", len(updates))

    async def push_rates(self, conn, updates, log):  # type: ignore[no-untyped-def]
        self.rates += updates
        self._log(log, "rates", len(updates))

    async def pull_bookings(self, conn, log):  # type: ignore[no-untyped-def]
        # Like the real providers: unconfirmed bookings are delivered again.
        return list(self.queue)

    async def confirm_bookings(self, conn, items, log):  # type: ignore[no-untyped-def]
        self.confirmed += items
        done = {i.message_id for i in items}
        self.queue = [b for b in self.queue if b.message_id not in done]


@pytest.fixture
def fake(monkeypatch) -> FakeAdapter:
    adapter = FakeAdapter()
    monkeypatch.setitem(registry.ADAPTERS, "siteminder", adapter)
    return adapter


async def room_type(admin: Api, code: str, rooms: int, start: int) -> str:
    rt = (
        await admin.post(
            admin.h("/room-types"),
            {
                "code": code,
                "name": {"en": code},
                "base_occupancy": 2,
                "max_occupancy": 3,
                "max_adults": 3,
                "max_children": 1,
                "base_price": "50.00",
            },
        )
    ).json()
    r = await admin.post(
        admin.h("/rooms/bulk"), {"room_type_id": rt["id"], "start": start, "end": start + rooms - 1}
    )
    assert r.status_code == 201, r.text
    return rt["id"]


@pytest.fixture
async def hotel(admin: Api) -> dict:
    rt = await room_type(admin, "STD", 3, 101)
    plans = (await admin.get(admin.h("/rate-plans"))).json()
    plan = next(p for p in plans if p["is_default"])
    r = await admin.post(
        admin.h("/channel-connections"),
        {
            "provider": "siteminder",
            "name": "SiteMinder",
            "account_code": "PMSXTEST",
            "username": "PMSTestUser",
            "password": "S3cret-Passw0rd",
            "hotel_code": "H1",
            "horizon_days": 60,
            "pull_reservations": True,
        },
    )
    assert r.status_code == 201, r.text
    conn = r.json()
    assert "password" not in conn and conn["status"]["state"] == "credentials_saved"
    r = await admin.put(
        admin.h(f"/channel-connections/{conn['id']}/mappings"),
        {
            "rooms": [{"room_type_id": rt, "external_code": "STD"}],
            "rates": [{"room_type_id": rt, "rate_plan_id": plan["id"], "external_code": "BAR"}],
        },
    )
    assert r.status_code == 200, r.text
    return {"rt": rt, "plan": plan["id"], "conn": conn["id"]}


async def book(admin: Api, rt: str, arrival: date, departure: date, **extra) -> dict:
    r = await admin.post(
        admin.h("/reservations"),
        {
            "arrival": arrival.isoformat(),
            "departure": departure.isoformat(),
            "guest": {"first_name": "Dara", "last_name": "Sok"},
            "rooms": [{"room_type_id": rt, "adults": 2}],
            "override_restrictions": True,
            **extra,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


async def status_of(conn_id: str) -> ChannelSyncStatus:
    async with owner_sessionmaker()() as db:
        status = await db.get(ChannelSyncStatus, conn_id)
        assert status is not None
        return status


async def dirty_count(conn_id: str) -> int:
    async with owner_sessionmaker()() as db:
        return await db.scalar(
            select(func.count())
            .select_from(ChannelDirtyRange)
            .where(ChannelDirtyRange.connection_id == conn_id)
        )


def later(minutes: int) -> datetime:
    return datetime.now(UTC) + timedelta(minutes=minutes)


# --- core: change queue and deltas ----------------------------------------------


async def test_first_sync_sends_the_horizon_then_only_what_changes(
    admin: Api, hotel: dict, fake: FakeAdapter
):
    await run_once()
    # Whole horizon, consecutive equal nights merged into ranges.
    assert fake.inventory == [InventoryUpdate("STD", d(0), d(59), 3)]
    assert [(r.start, r.end) for r in fake.restrictions] == [(d(0), d(59))]
    first = fake.restrictions[0]
    assert (
        first.closed,
        first.closed_to_arrival,
        first.closed_to_departure,
        first.min_stay,
        first.max_stay,
    ) == (
        False,
        False,
        False,
        0,
        0,
    )
    assert fake.rates and fake.rates[0].start == d(0) and fake.rates[-1].end == d(59)
    status = await status_of(hotel["conn"])
    assert status.state == "test_ok" and status.horizon_end == d(60) and await dirty_count(hotel["conn"]) == 0

    # Nothing changed: nothing is sent (provider rule: delta updates only).
    fake.reset()
    await run_once(later(1))
    assert (fake.inventory, fake.restrictions, fake.rates) == ([], [], [])

    # A reservation: the trigger queued the nights; only availability is sent.
    await book(admin, hotel["rt"], d(5), d(7))
    assert await dirty_count(hotel["conn"]) >= 1
    await run_once(later(2))
    assert fake.inventory == [InventoryUpdate("STD", d(5), d(6), 2)]
    assert fake.restrictions == [] and fake.rates == []

    # A price change for one night: only that rate.
    fake.reset()
    r = await admin.post(
        admin.h("/rates/bulk"),
        {
            "rate_plan_ids": [hotel["plan"]],
            "room_type_ids": [hotel["rt"]],
            "start": d(10).isoformat(),
            "end": d(10).isoformat(),
            "price": {"mode": "set", "value": "80.00"},
        },
    )
    assert r.status_code == 200, r.text
    await run_once(later(3))
    assert [(u.start, u.end, u.amount, u.currency) for u in fake.rates] == [
        (d(10), d(10), Decimal("80.00"), "USD")
    ]
    assert fake.inventory == [] and fake.restrictions == []

    # A stop sell and a minimum stay: only the restriction that changed.
    fake.reset()
    await admin.post(
        admin.h("/rates/bulk"),
        {
            "rate_plan_ids": [hotel["plan"]],
            "room_type_ids": [hotel["rt"]],
            "start": d(12).isoformat(),
            "end": d(13).isoformat(),
            "restrictions": {"min_stay": 2},
        },
    )
    await run_once(later(4))
    assert fake.restrictions == [RestrictionUpdate("STD", "BAR", d(12), d(13), min_stay=2)]

    # A room blocked for maintenance: availability only.
    fake.reset()
    rooms = (await admin.get(admin.h("/rooms"))).json()
    r = await admin.post(
        admin.h("/room-blocks"),
        {"room_id": rooms[0]["id"], "start_date": d(20).isoformat(), "end_date": d(22).isoformat()},
    )
    assert r.status_code == 201, r.text
    await run_once(later(5))
    assert fake.inventory == [InventoryUpdate("STD", d(20), d(21), 2)]

    # The exchange log was kept (redacted bodies).
    async with owner_sessionmaker()() as db:
        assert await db.scalar(select(func.count()).select_from(ChannelMessage)) >= 6


async def test_failure_keeps_the_changes_and_backs_off(admin: Api, hotel: dict, fake: FakeAdapter):
    await run_once()
    fake.reset()
    await book(admin, hotel["rt"], d(3), d(4))
    fake.fail = ChannelError(ErrorKind.TRANSIENT, "HTTP 503")
    await run_once(later(1))
    status = await status_of(hotel["conn"])
    assert status.state == "degraded" and status.consecutive_failures == 1
    assert status.next_push_at is not None and status.next_push_at > later(1)
    assert "503" in (status.last_error or "")
    assert await dirty_count(hotel["conn"]) >= 1  # nothing lost

    fake.fail = None
    await run_once(later(1))  # still waiting for the retry delay
    assert fake.inventory == []
    await run_once(later(10))
    assert fake.inventory == [InventoryUpdate("STD", d(3), d(3), 2)]
    status = await status_of(hotel["conn"])
    assert status.state == "test_ok" and status.consecutive_failures == 0
    assert await dirty_count(hotel["conn"]) == 0

    conn = (await admin.get(admin.h(f"/channel-connections/{hotel['conn']}"))).json()
    assert conn["errors_24h"] >= 1 and conn["pending_changes"] == 0


async def test_paused_connection_accumulates_changes(admin: Api, hotel: dict, fake: FakeAdapter):
    await run_once()
    conn = (await admin.get(admin.h(f"/channel-connections/{hotel['conn']}"))).json()
    r = await admin.patch(
        admin.h(f"/channel-connections/{hotel['conn']}"), {"version": conn["version"], "enabled": False}
    )
    assert r.status_code == 200 and r.json()["status"]["state"] == "paused"
    fake.reset()
    await book(admin, hotel["rt"], d(8), d(9))
    await run_once(later(1))
    assert fake.inventory == [] and await dirty_count(hotel["conn"]) >= 1
    r = await admin.patch(
        admin.h(f"/channel-connections/{hotel['conn']}"), {"version": r.json()["version"], "enabled": True}
    )
    await run_once(later(2))
    assert fake.inventory == [InventoryUpdate("STD", d(8), d(8), 2)]


async def test_switching_sending_off_and_on_sends_the_horizon_again(
    admin: Api, hotel: dict, fake: FakeAdapter
):
    await run_once()
    conn = (await admin.get(admin.h(f"/channel-connections/{hotel['conn']}"))).json()
    r = await admin.patch(
        admin.h(f"/channel-connections/{hotel['conn']}"), {"version": conn["version"], "push_ari": False}
    )
    await book(admin, hotel["rt"], d(2), d(3))
    assert r.json()["pending_changes"] == 0 and await dirty_count(hotel["conn"]) == 0  # nothing queued
    fake.reset()
    r = await admin.patch(
        admin.h(f"/channel-connections/{hotel['conn']}"), {"version": r.json()["version"], "push_ari": True}
    )
    assert r.status_code == 200, r.text
    await run_once(later(1))
    assert fake.inventory == [
        InventoryUpdate("STD", d(0), d(1), 3),
        InventoryUpdate("STD", d(2), d(2), 2),
        InventoryUpdate("STD", d(3), d(59), 3),
    ]


async def test_full_refresh_is_limited_to_once_a_day(admin: Api, hotel: dict, fake: FakeAdapter):
    await run_once()
    fake.reset()
    r = await admin.post(admin.h(f"/channel-connections/{hotel['conn']}/full-refresh"))
    assert r.status_code == 202
    await run_once(later(1))
    assert fake.inventory == [InventoryUpdate("STD", d(0), d(59), 3)]
    r = await admin.post(admin.h(f"/channel-connections/{hotel['conn']}/full-refresh"))
    assert r.status_code == 409 and error_code(r) == "FULL_REFRESH_TOO_SOON"


# --- core: reservations from the channel -------------------------------------------


def channel_booking(
    message_id: str,
    action: str,
    arrival: date,
    departure: date,
    *,
    external_id: str = "SM-1001",
    at: datetime | None = None,
    room: str = "STD",
    amount: str = "66.00",
    code: str = "BDC",
) -> InboundBooking:
    nights = [
        InboundNight(arrival + timedelta(days=i), Decimal(amount), "BAR")
        for i in range((departure - arrival).days)
    ]
    return InboundBooking(
        external_id=external_id,
        message_id=message_id,
        action=action,
        message_at=at or datetime.now(UTC),
        hotel_code="H1",
        channel_code=code,
        channel_name="Booking.com" if code == "BDC" else code,
        channel_reference=f"BDC-{external_id}",
        currency="USD",
        amounts_after_tax=True,
        total=Decimal(amount) * len(nights),
        stays=[InboundStay(room, "BAR", arrival, departure, 2, 0, nights, None, ["Late arrival"])],
        booker=InboundGuest("Mei", "Lin", "mei.lin@example.com", "+855 12 345 678", "KH"),
        comments=["Late arrival"],
        card_brand="VI",
        card_last4="1111",
    )


async def reservation(admin: Api, res_id: str) -> dict:
    r = await admin.get(admin.h(f"/reservations/{res_id}"))
    assert r.status_code == 200, r.text
    return r.json()


async def test_booking_modification_and_cancellation_from_the_channel(
    admin: Api, hotel: dict, fake: FakeAdapter
):
    # 10 % VAT added on top of prices: the channel's 66.00 after tax is a 60.00 price.
    r = await admin.post(
        admin.h("/tax-rates"),
        {
            "code": "VAT",
            "name": {"en": "VAT"},
            "rate": "10",
            "is_inclusive": False,
            "applies_to": "accommodation",
        },
    )
    assert r.status_code == 201, r.text
    await run_once()
    fake.reset()
    t0 = datetime.now(UTC) - timedelta(hours=1)
    fake.queue.append(channel_booking("m1", "book", d(10), d(12), at=t0))
    await run_once(later(5))
    assert len(fake.confirmed) == 1 and fake.confirmed[0].ok
    async with owner_sessionmaker()() as db:
        row = (await db.scalars(select(ChannelBooking))).one()
        assert row.import_status == "imported" and row.card_last4 == "1111"
        assert "1111" not in json.dumps(row.data)  # card data is never in the stored booking
    res = await reservation(admin, str(row.reservation_id))
    assert fake.confirmed[0].pms_reference == res["code"]
    assert (
        res["source"] == "booking_com"
        and res["external_ref"] == "BDC-SM-1001"
        and res["status"] == "confirmed"
    )
    assert [n["price"] for n in res["rooms"][0]["nights"]] == ["60.00", "60.00"]
    assert {n["price_source"] for n in res["rooms"][0]["nights"]} == {"channel"}
    assert res["booker"]["last_name"] == "Lin" and res["special_requests"] == "Late arrival"
    assert "••••1111" in res["internal_notes"]
    assert Decimal(res["grand_total"]) == Decimal("132.00")
    # Availability goes back to the channel (provider requirement after every import).
    await run_once(later(6))
    assert InventoryUpdate("STD", d(10), d(11), 2) in fake.inventory

    # The same revision delivered again: not imported twice.
    fake.queue.append(channel_booking("m1", "book", d(10), d(12), at=t0))
    await run_once(later(10))
    async with owner_sessionmaker()() as db:
        assert await db.scalar(select(func.count()).select_from(ChannelBooking)) == 1
    assert (await admin.get(admin.h("/reservations"))).json()["total"] == 1

    # Modification: same reservation (same code), new dates and prices.
    fake.queue.append(
        channel_booking("m2", "modify", d(11), d(14), at=t0 + timedelta(minutes=5), amount="77.00")
    )
    await run_once(later(20))
    res2 = await reservation(admin, res["id"])
    assert res2["code"] == res["code"] and (res2["arrival"], res2["departure"]) == (
        d(11).isoformat(),
        d(14).isoformat(),
    )
    assert [n["price"] for n in res2["rooms"][0]["nights"]] == ["70.00", "70.00", "70.00"]

    # Cancellation: cancelled without a fee (the channel applies its own terms).
    fake.queue.append(channel_booking("m3", "cancel", d(11), d(14), at=t0 + timedelta(minutes=9)))
    await run_once(later(30))
    res3 = await reservation(admin, res["id"])
    assert res3["status"] == "cancelled" and Decimal(res3["charges_total"]) == 0
    assert all(c.ok for c in fake.confirmed)


async def test_messages_out_of_order(admin: Api, hotel: dict, fake: FakeAdapter):
    await run_once()
    t0 = datetime.now(UTC) - timedelta(hours=2)
    # The modification arrives before the booking: it creates the reservation.
    fake.queue.append(channel_booking("m2", "modify", d(6), d(8), at=t0 + timedelta(minutes=10)))
    await run_once(later(5))
    # The older original booking then arrives: ignored (already superseded).
    fake.queue.append(channel_booking("m1", "book", d(5), d(7), at=t0))
    # A cancellation of a booking never received: ignored, acknowledged.
    fake.queue.append(channel_booking("x1", "cancel", d(5), d(7), external_id="SM-9999"))
    await run_once(later(10))
    async with owner_sessionmaker()() as db:
        rows = {r.revision: r for r in await db.scalars(select(ChannelBooking))}
    assert rows["m2"].import_status == "imported"
    assert (rows["m1"].import_status, rows["m1"].error_code) == ("ignored", "OLDER_REVISION")
    assert (rows["x1"].import_status, rows["x1"].error_code) == ("ignored", "UNKNOWN_BOOKING")
    res = await reservation(admin, str(rows["m2"].reservation_id))
    assert (res["arrival"], res["departure"]) == (d(6).isoformat(), d(8).isoformat())
    assert all(c.ok for c in fake.confirmed) and len(fake.confirmed) == 3


async def test_channel_booking_is_never_refused_but_overbooking_is_flagged(
    admin: Api, hotel: dict, fake: FakeAdapter
):
    await run_once()
    for _ in range(3):
        await book(admin, hotel["rt"], d(15), d(16))  # the category is now sold out
    fake.queue.append(channel_booking("m1", "book", d(15), d(16)))
    await run_once(later(5))
    async with owner_sessionmaker()() as db:
        row = (await db.scalars(select(ChannelBooking))).one()
    assert row.import_status == "imported" and row.overbooked
    assert (await reservation(admin, str(row.reservation_id)))["is_overbooked"] is True
    attention = (await admin.get(admin.h("/channel-bookings"), params={"attention": "true"})).json()
    assert [b["external_id"] for b in attention] == ["SM-1001"]
    # The channel is told there is nothing left (availability never negative).
    assert InventoryUpdate("STD", d(15), d(15), 0) in fake.inventory


async def test_unmapped_room_is_reported_then_imported_after_mapping(
    admin: Api, hotel: dict, fake: FakeAdapter
):
    dlx = await room_type(admin, "DLX", 1, 201)
    await run_once()
    fake.queue.append(channel_booking("m1", "book", d(4), d(6), room="DLX"))
    await run_once(later(5))
    assert len(fake.confirmed) == 1 and not fake.confirmed[0].ok
    assert "UNMAPPED_ROOM" in (fake.confirmed[0].error_text or "")
    failed = (await admin.get(admin.h("/channel-bookings"), params={"status": "failed"})).json()
    assert failed[0]["error_code"] == "UNMAPPED_ROOM" and failed[0]["guest_name"] == "Mei Lin"

    mappings = (await admin.get(admin.h(f"/channel-connections/{hotel['conn']}/mappings"))).json()
    r = await admin.put(
        admin.h(f"/channel-connections/{hotel['conn']}/mappings"),
        {
            "rooms": [*mappings["rooms"], {"room_type_id": dlx, "external_code": "DLX"}],
            "rates": mappings["rates"],
        },
    )
    assert r.status_code == 200, r.text
    r = await admin.post(admin.h(f"/channel-bookings/{failed[0]['id']}/retry"))
    assert r.status_code == 200, r.text
    assert r.json()["import_status"] == "imported" and r.json()["reservation_code"]


async def test_connection_api_rules(admin: Api, hotel: dict, fake: FakeAdapter, user_factory):
    # Credentials are write-only and never in the audit log.
    conn = (await admin.get(admin.h(f"/channel-connections/{hotel['conn']}"))).json()
    assert "password" not in conn
    r = await admin.patch(
        admin.h(f"/channel-connections/{hotel['conn']}"),
        {"version": conn["version"], "password": "N3w-Passw0rd!"},
    )
    assert r.status_code == 200, r.text
    # Password and another field together (one versioned edit).
    r = await admin.patch(
        admin.h(f"/channel-connections/{hotel['conn']}"),
        {"version": r.json()["version"], "name": "SiteMinder (BDC + Agoda)", "password": "An0ther-Passw0rd"},
    )
    assert r.status_code == 200, r.text
    assert (
        r.json()["name"] == "SiteMinder (BDC + Agoda)" and r.json()["status"]["state"] == "credentials_saved"
    )
    from app.core.audit import AuditLog

    async with owner_sessionmaker()() as db:
        logs = list(await db.scalars(select(AuditLog).where(AuditLog.entity_type == "channel_connection")))
    assert logs and all("Passw0rd" not in json.dumps(log.changes or {}) for log in logs)
    # Provider rules: no XML special characters in credentials; production needs its endpoint.
    bad = await admin.patch(
        admin.h(f"/channel-connections/{hotel['conn']}"),
        {"version": r.json()["version"], "password": "a<b&c"},
    )
    assert bad.status_code == 422
    prod = await admin.patch(
        admin.h(f"/channel-connections/{hotel['conn']}"),
        {"version": r.json()["version"], "environment": "production"},
    )
    assert prod.status_code == 422 and error_code(prod) == "ENDPOINT_REQUIRED"
    # Test connection is a real adapter call (here the in-memory one) and updates the state.
    t = await admin.post(admin.h(f"/channel-connections/{hotel['conn']}/test"))
    assert t.status_code == 200 and t.json()["ok"] and t.json()["state"] == "test_ok"
    # Receptionists may not see the channel manager.
    clerk = await user_factory("receptionist")
    assert (await clerk.get(clerk.h("/channel-connections"))).status_code == 403


# --- SiteMinder adapter: contract with the official samples ----------------------------

CONN = ConnectionConfig(None, "test", "PMSCODE", "USERNAME", "PASSWORD", "HOTELCODE")
VOLATILE = {"EchoToken", "TimeStamp"}


def canonical(el: ET.Element) -> tuple:
    """Element tree without whitespace, comments, EchoToken and TimeStamp, with
    date-time attributes compared as instants."""
    attrs = {}
    for k, v in el.attrib.items():
        if k in VOLATILE:
            continue
        if k in ("CreateDateTime", "LastModifyDateTime"):
            v = datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(UTC).isoformat()
        attrs[k] = v
    text = (el.text or "").strip()
    return (el.tag.lower(), tuple(sorted(attrs.items())), text, tuple(canonical(c) for c in el))


def fixture(name: str) -> ET.Element:
    return ET.fromstring((FIXTURES / name).read_text())  # noqa: S314 (trusted test fixture)


def body_of(envelope: ET.Element) -> ET.Element:
    return envelope.find("{http://schemas.xmlsoap.org/soap/envelope/}Body")[0]  # type: ignore[index]


def built(el: ET.Element) -> ET.Element:
    """Our message, serialised and parsed back (what goes on the wire)."""
    return ET.fromstring(ET.tostring(el))  # noqa: S314


def test_serialisation_ignores_the_global_namespace_registry():
    """Other libraries (the PDF renderer) register a default XML namespace in
    ElementTree's process-wide registry; our messages must not change."""
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    adapter = SiteMinderAdapter()
    body = adapter.envelope(CONN, adapter.read_request(CONN)).decode()
    assert '<OTA_ReadRQ xmlns="http://www.opentravel.org/OTA/2003/05"' in body and "ns0:" not in body


def test_availability_message_matches_official_sample():
    adapter = SiteMinderAdapter()
    ours = adapter.availability_message(
        CONN, [InventoryUpdate("SUP", date(2025, 3, 1), date(2025, 3, 1), 10)]
    )
    assert canonical(built(ours)) == canonical(fixture("avail_single_date.xml"))


def test_full_envelope_matches_the_minified_official_request():
    official = (
        '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/"><SOAP-ENV:Header>'
        '<wsse:Security xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"'
        ' SOAP-ENV:mustUnderstand="1"><wsse:UsernameToken><wsse:Username>USERNAME</wsse:Username>'
        '<wsse:Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0'
        '#PasswordText">PASSWORD</wsse:Password></wsse:UsernameToken></wsse:Security></SOAP-ENV:Header>'
        '<SOAP-ENV:Body><OTA_HotelAvailNotifRQ xmlns="http://www.opentravel.org/OTA/2003/05" Version="1.0" '
        'TimeStamp="2024-07-06T15:27:41Z" EchoToken="ed8835ff-6198-4f38-b589-3058397f677c"><POS><Source>'
        '<RequestorID Type="22" ID="PMSCODE"/></Source></POS><AvailStatusMessages HotelCode="HOTELCODE">'
        '<AvailStatusMessage BookingLimit="10"><StatusApplicationControl Start="2025-03-01" End="2025-03-01" '
        'InvTypeCode="SUP"/></AvailStatusMessage></AvailStatusMessages></OTA_HotelAvailNotifRQ></SOAP-ENV:Body>'
        "</SOAP-ENV:Envelope>"
    )
    adapter = SiteMinderAdapter()
    ours = adapter.envelope(
        CONN,
        adapter.availability_message(CONN, [InventoryUpdate("SUP", date(2025, 3, 1), date(2025, 3, 1), 10)]),
    )
    assert b"\n" not in ours  # minified, as required in production
    assert canonical(ET.fromstring(ours)) == canonical(ET.fromstring(official))  # noqa: S314


@pytest.mark.parametrize(
    ("sample", "update"),
    [
        ("restriction_stop_sell_close.xml", {"closed": True}),
        ("restriction_cta_open.xml", {"closed_to_arrival": False}),
        ("restriction_min_los_7.xml", {"min_stay": 7}),
        ("restriction_remove_max_los.xml", {"max_stay": 0}),
    ],
)
def test_restriction_messages_match_official_samples(sample: str, update: dict):
    official = fixture(sample)
    ctrl = official.find(".//{http://www.opentravel.org/OTA/2003/05}StatusApplicationControl")
    assert ctrl is not None
    u = RestrictionUpdate(
        ctrl.get("InvTypeCode", ""),
        ctrl.get("RatePlanCode", ""),
        date.fromisoformat(ctrl.get("Start", "")),
        date.fromisoformat(ctrl.get("End", "")),
        **update,
    )
    hotel = official.find("{http://www.opentravel.org/OTA/2003/05}AvailStatusMessages").get("HotelCode")  # type: ignore[union-attr]
    conn = ConnectionConfig(None, "test", "PMSCODE", "U", "P", hotel or "")
    assert canonical(built(SiteMinderAdapter().restriction_message(conn, [u]))) == canonical(official)


def test_rate_message_matches_official_pdp_sample():
    conn = ConnectionConfig(None, "test", "PMSCODE", "U", "P", "HOTEL")
    u = RateUpdate("SUP", "BAR", date(2025, 3, 1), date(2025, 3, 14), Decimal("123"), "AUD", True)
    assert canonical(built(SiteMinderAdapter().rate_message(conn, [u]))) == canonical(
        fixture("rates_pdp.xml")
    )


def test_read_and_confirm_messages_match_official_samples():
    adapter = SiteMinderAdapter()
    conn = ConnectionConfig(None, "test", "{PMSCODE}", "U", "P", "{HOTELCODE}")
    assert canonical(built(adapter.read_request(conn))) == canonical(fixture("read_rq_hotel_level.xml"))
    item = ConfirmItem(
        message_id="qlmumfgwx85nlkgmtb",
        external_id="x",
        action="book",
        ok=True,
        pms_reference="ABC-1234567890",
        at=datetime.fromisoformat("2025-08-20T09:28:47+02:00"),
    )
    ours = built(adapter.notif_report(CONN, [item], True))
    assert canonical(ours) == canonical(body_of(fixture("confirm_reservation.xml")))


def test_responses_are_classified():
    parse = SiteMinderAdapter._parse_soap
    assert parse(200, (FIXTURES / "rates_success.xml").read_text()) is not None
    cases = {
        "error_invalid_credentials.xml": ErrorKind.AUTH,
        "error_invalid_hotel.xml": ErrorKind.CONFIG,
        "fault_payload_too_large.xml": ErrorKind.DATA,
    }
    for name, kind in cases.items():
        with pytest.raises(ChannelError) as exc:
            parse(200, (FIXTURES / name).read_text())
        assert exc.value.kind == kind, name
    with pytest.raises(ChannelError) as exc:
        parse(503, "Service Unavailable")
    assert exc.value.kind == ErrorKind.TRANSIENT and exc.value.retryable


def test_official_reservation_sample_is_parsed_without_keeping_the_card_number():
    env = fixture("res_retrieve_max_content.xml")
    [b] = parse_reservations(body_of(env))
    assert (b.external_id, b.message_id, b.action) == ("ABC-1234567890", "isuokfr1pyc2ntest7", "book")
    assert (b.channel_code, b.channel_name, b.channel_reference) == ("EXP", "Expedia", "1234567890")
    assert (b.currency, b.total, b.amounts_after_tax, b.hotel_code) == (
        "USD",
        Decimal("583.25"),
        True,
        "10107",
    )
    [s] = b.stays
    assert (s.room_code, s.rate_code, s.arrival, s.departure) == (
        "DR",
        "RAC1",
        date(2013, 3, 12),
        date(2013, 3, 15),
    )
    assert (s.adults, s.children) == (1, 2)
    # Per-day Total (rate + extras), split by rate plan as in the message.
    assert [(n.night, n.amount, n.rate_code) for n in s.nights] == [
        (date(2013, 3, 12), Decimal("222.75"), "RAC1"),
        (date(2013, 3, 13), Decimal("222.75"), "RAC1"),
        (date(2013, 3, 14), Decimal("112.75"), "RAC2"),
    ]
    assert b.booker is not None and (b.booker.first_name, b.booker.last_name) == ("James", "Bond")
    assert b.booker.email == "james.bond@mi5.co.uk" and b.booker.phone == "555-1234"
    assert (b.card_brand, b.card_last4) == ("VI", "4444")
    assert "4444444444444444" not in repr(b)
    assert "will be arriving after 6 pm" in b.comments and "ArrivalDetails: Arriving by coach" in b.comments
    assert b.extra["deposit"] == "291.63" and len(b.extra["services"]) == 4

    [m] = parse_reservations(body_of(fixture("res_retrieve_min_content_fixed.xml")))
    assert m.stays[0].nights == [] and m.booker is not None and m.booker.last_name == "Bond"
    assert parse_reservations(fixture("res_retrieve_empty.xml")) == []


async def test_siteminder_pull_end_to_end_over_http(admin: Api, hotel: dict, monkeypatch):
    """The real adapter and its HTTP layer, against a transport answering with
    SiteMinder's sample messages (dates moved into the future)."""
    sample = (FIXTURES / "res_retrieve_max_content.xml").read_text()
    for old, new in (("2013-03-12", d(30)), ("2013-03-14", d(32)), ("2013-03-15", d(33))):
        sample = sample.replace(old, new.isoformat())
    sample = sample.replace('HotelCode="10107"', 'HotelCode="H1"').replace(
        'HotelCode="HOTELCODE"', 'HotelCode="H1"'
    )
    sent: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/webservices/PMSXTEST"
        assert request.headers["content-type"] == "text/xml; charset=utf-8"
        sent.append(request.content)
        if b"OTA_ReadRQ" in request.content:
            return httpx.Response(200, text=sample)
        root = "OTA_NotifReportRS" if b"OTA_NotifReportRQ" in request.content else "OTA_HotelAvailNotifRS"
        if b"OTA_HotelRateAmountNotifRQ" in request.content:
            root = "OTA_HotelRateAmountNotifRS"
        return httpx.Response(
            200,
            text=(
                '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/">'
                "<SOAP-ENV:Header/>"
                f'<SOAP-ENV:Body><{root} xmlns="http://www.opentravel.org/OTA/2003/05" Version="1.0">'
                "<Success/>"
                f"</{root}></SOAP-ENV:Body></SOAP-ENV:Envelope>"
            ),
        )

    monkeypatch.setitem(registry.ADAPTERS, "siteminder", SiteMinderAdapter(httpx.MockTransport(handler)))
    mappings = (await admin.get(admin.h(f"/channel-connections/{hotel['conn']}/mappings"))).json()
    r = await admin.put(
        admin.h(f"/channel-connections/{hotel['conn']}/mappings"),
        {
            "rooms": [{"room_type_id": hotel["rt"], "external_code": "DR"}],
            "rates": [{**mappings["rates"][0], "external_code": "RAC1"}],
        },
    )
    assert r.status_code == 200, r.text
    await run_once()
    async with owner_sessionmaker()() as db:
        row = (await db.scalars(select(ChannelBooking))).one()
        messages = list(await db.scalars(select(ChannelMessage)))
    assert row.import_status == "imported", (row.error_code, row.error_detail)
    res = await reservation(admin, str(row.reservation_id))
    assert res["source"] == "other" and res["external_ref"] == "1234567890"
    confirm = next(m for m in sent if b"OTA_NotifReportRQ" in m)
    assert b'ID="isuokfr1pyc2ntest7"' in confirm and f'ResID_Value="{res["code"]}"'.encode() in confirm
    assert b"<Success />" in confirm or b"<Success/>" in confirm
    # The provider received the password; the stored log never contains it, nor the card number.
    assert all(b"S3cret-Passw0rd" in m for m in sent)
    stored = " ".join((m.request_body or "") + (m.response_body or "") for m in messages)
    assert "S3cret-Passw0rd" not in stored and "4444444444444444" not in stored
    assert "4444444444444444" not in json.dumps(row.data)
