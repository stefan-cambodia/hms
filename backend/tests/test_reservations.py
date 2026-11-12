"""Phase 4 — reservation engine, inventory integrity, pricing, guests."""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.db import sessionmaker
from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD, Api, error_code, new_client

D0 = date.today() + timedelta(days=30)


def d(offset: int) -> str:
    return (D0 + timedelta(days=offset)).isoformat()


@pytest.fixture
async def hotel(admin: Api) -> dict:
    """One category (STD) with two rooms, VAT 10% + city tax 1.00 per person-night."""
    rt = (
        await admin.post(
            admin.h("/room-types"),
            {
                "code": "STD",
                "name": {"en": "Standard"},
                "base_occupancy": 2,
                "max_occupancy": 3,
                "max_adults": 3,
                "max_children": 1,
                "base_price": "50.00",
                "extra_adult_price": "10.00",
                "extra_child_price": "5.00",
            },
        )
    ).json()
    rooms = (
        await admin.post(admin.h("/rooms/bulk"), {"room_type_id": rt["id"], "start": 101, "end": 102})
    ).json()
    await admin.post(
        admin.h("/tax-rates"), {"code": "VAT", "name": {"en": "VAT"}, "kind": "percent", "rate": "10"}
    )
    await admin.post(
        admin.h("/tax-rates"),
        {
            "code": "CITY",
            "name": {"en": "City tax"},
            "kind": "fixed_per_person_night",
            "rate": "1.00",
            "applies_to": "accommodation",
        },
    )
    return {"rt": rt["id"], "r101": rooms[0]["id"], "r102": rooms[1]["id"]}


def booking(
    hotel: dict,
    arrival: int,
    departure: int,
    *,
    room: str | None = None,
    adults: int = 2,
    children: int = 0,
    guest: dict | None = None,
    **extra,
) -> dict:
    return {
        "arrival": d(arrival),
        "departure": d(departure),
        "guest": guest or {"first_name": "Dara", "last_name": "Sok", "email": "dara@example.com"},
        "rooms": [{"room_type_id": hotel["rt"], "room_id": room, "adults": adults, "children": children}],
        **extra,
    }


async def test_quote_and_create_with_prices_and_taxes(admin: Api, hotel):
    q = await admin.post(
        admin.h("/reservations/quote"),
        {"arrival": d(0), "departure": d(2), "rooms": [{"room_type_id": hotel["rt"], "adults": 3}]},
    )
    assert q.status_code == 200, q.text
    body = q.json()
    # 50 base + 10 for the third adult, two nights.
    assert [n["price"] for n in body["rooms"][0]] == ["60.00", "60.00"]
    assert body["accommodation_total"] == "120.00"
    assert {t["code"]: t["amount"] for t in body["taxes"]} == {"VAT": "12.00", "CITY": "6.00"}
    assert body["grand_total"] == "138.00"

    r = await admin.post(admin.h("/reservations"), booking(hotel, 0, 2, adults=3))
    assert r.status_code == 201, r.text
    res = r.json()
    assert res["code"] == "R000001" and res["status"] == "confirmed"
    assert res["grand_total"] == "138.00" and res["balance"] == "138.00"
    assert res["booker"]["last_name"] == "Sok"
    assert res["is_modified"] is False
    history = (await admin.get(admin.h(f"/reservations/{res['id']}/events"))).json()
    assert [e["action"] for e in history] == ["created"]
    logs = (await admin.get(admin.h("/audit-logs"), params={"entity_type": "reservation"})).json()
    assert logs["items"][0]["action"] == "reservation.created"


async def test_same_room_cannot_be_allocated_twice(admin: Api, hotel):
    first = await admin.post(admin.h("/reservations"), booking(hotel, 0, 2, room=hotel["r101"]))
    assert first.status_code == 201
    clash = await admin.post(admin.h("/reservations"), booking(hotel, 1, 3, room=hotel["r101"]))
    assert clash.status_code == 409 and error_code(clash) == "ROOM_UNAVAILABLE"
    # Departure day is free for the next arrival.
    back_to_back = await admin.post(admin.h("/reservations"), booking(hotel, 2, 4, room=hotel["r101"]))
    assert back_to_back.status_code == 201


async def test_database_rejects_overlap_even_without_the_api(admin: Api, hotel):
    r = (await admin.post(admin.h("/reservations"), booking(hotel, 0, 3, room=hotel["r101"]))).json()
    async with sessionmaker()() as db:
        with pytest.raises(IntegrityError, match="ex_room_allocations_no_overlap"):
            await db.execute(
                text(
                    "INSERT INTO reservation_rooms (id, hotel_id, reservation_id, room_type_id, room_id,"
                    " arrival, departure, adults, children)"
                    " SELECT :id, hotel_id, id, :rt, :room, :a, :b, 1, 0"
                    " FROM reservations WHERE id = :res"
                ),
                {
                    "id": uuid.uuid4(),
                    "rt": uuid.UUID(hotel["rt"]),
                    "room": uuid.UUID(hotel["r101"]),
                    "a": D0 + timedelta(days=1),
                    "b": D0 + timedelta(days=5),
                    "res": uuid.UUID(r["id"]),
                },
            )


async def _parallel_clients(admin: Api, n: int) -> list[Api]:
    apis = []
    for _ in range(n):
        api = Api(new_client(), admin.hotel_id)
        await api.login(ADMIN_EMAIL, ADMIN_PASSWORD)
        apis.append(api)
    return apis


async def test_concurrent_bookings_of_the_same_room(admin: Api, hotel):
    """Ten devices try to book room 101 for overlapping dates at the same time."""
    apis = await _parallel_clients(admin, 10)
    try:
        results = await asyncio.gather(
            *[
                a.post(
                    a.h("/reservations"),
                    booking(
                        hotel,
                        i % 3,
                        3 + i % 2,
                        room=hotel["r101"],
                        guest={"first_name": f"G{i}", "last_name": "Race"},
                    ),
                )
                for i, a in enumerate(apis)
            ]
        )
    finally:
        for a in apis:
            await a.client.aclose()
    codes = sorted(r.status_code for r in results)
    assert codes.count(201) == 1, codes
    assert all(error_code(r) == "ROOM_UNAVAILABLE" for r in results if r.status_code == 409)
    async with sessionmaker()() as db:
        n = await db.scalar(
            text("SELECT count(*) FROM room_allocations WHERE room_id = :r"), {"r": uuid.UUID(hotel["r101"])}
        )
    assert n == 1


async def test_concurrent_category_bookings_never_oversell(admin: Api, hotel):
    """Six unassigned bookings race for a category with two rooms."""
    apis = await _parallel_clients(admin, 6)
    try:
        results = await asyncio.gather(
            *[
                a.post(
                    a.h("/reservations"),
                    booking(hotel, 0, 2, guest={"first_name": f"G{i}", "last_name": "Race"}),
                )
                for i, a in enumerate(apis)
            ]
        )
    finally:
        for a in apis:
            await a.client.aclose()
    statuses = [r.status_code for r in results]
    assert statuses.count(201) == 2, statuses
    assert all(error_code(r) == "NO_AVAILABILITY" for r in results if r.status_code == 409)
    avail = (await admin.get(admin.h("/availability"), params={"start": d(0), "end": d(2)})).json()
    assert [n["available"] for n in avail[0]["nights"]] == [0, 0]


async def test_overbooking_needs_explicit_permission(admin: Api, hotel, user_factory):
    for i in range(2):
        await admin.post(
            admin.h("/reservations"), booking(hotel, 0, 1, guest={"first_name": f"A{i}", "last_name": "X"})
        )
    clerk = await user_factory("receptionist")
    r = await clerk.post(clerk.h("/reservations"), booking(hotel, 0, 1, allow_overbooking=True))
    assert r.status_code == 403
    r = await clerk.post(clerk.h("/reservations"), booking(hotel, 0, 1))
    assert r.status_code == 409 and error_code(r) == "NO_AVAILABILITY"
    r = await admin.post(admin.h("/reservations"), booking(hotel, 0, 1, allow_overbooking=True))
    assert r.status_code == 201 and r.json()["is_overbooked"] is True


async def test_room_blocks_take_rooms_out_of_sale(admin: Api, hotel):
    r = await admin.post(
        admin.h("/room-blocks"),
        {"room_id": hotel["r102"], "start_date": d(0), "end_date": d(5), "reason": "maintenance"},
    )
    assert r.status_code == 201, r.text
    avail = (await admin.get(admin.h("/availability"), params={"start": d(0), "end": d(1)})).json()
    assert avail[0]["nights"][0] == {"night": d(0), "total": 2, "available": 1}
    clash = await admin.post(admin.h("/reservations"), booking(hotel, 2, 3, room=hotel["r102"]))
    assert error_code(clash) == "ROOM_UNAVAILABLE"
    await admin.post(admin.h("/reservations"), booking(hotel, 10, 12, room=hotel["r101"]))
    r = await admin.post(
        admin.h("/room-blocks"), {"room_id": hotel["r101"], "start_date": d(11), "end_date": d(13)}
    )
    assert r.status_code == 409 and error_code(r) == "ROOM_UNAVAILABLE"
    # Blocking the last free room of a sold category is refused too.
    await admin.post(admin.h("/reservations"), booking(hotel, 20, 21))
    r = await admin.post(
        admin.h("/room-blocks"), {"room_id": hotel["r101"], "start_date": d(20), "end_date": d(21)}
    )
    assert r.status_code == 201  # 102 can still take the unassigned booking
    r = await admin.post(
        admin.h("/room-blocks"), {"room_id": hotel["r102"], "start_date": d(20), "end_date": d(21)}
    )
    assert r.status_code == 409


async def test_cancel_releases_inventory_and_follows_state_machine(admin: Api, hotel):
    res = (await admin.post(admin.h("/reservations"), booking(hotel, 0, 2, room=hotel["r101"]))).json()
    stale = res["version"]
    r = await admin.post(
        admin.h(f"/reservations/{res['id']}/cancel"), {"version": res["version"], "reason": "Guest request"}
    )
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert r.json()["grand_total"] == "0.00"
    # The room is free again.
    assert (
        await admin.post(admin.h("/reservations"), booking(hotel, 0, 2, room=hotel["r101"]))
    ).status_code == 201
    again = await admin.post(
        admin.h(f"/reservations/{res['id']}/cancel"), {"version": r.json()["version"], "reason": "x"}
    )
    assert error_code(again) == "INVALID_STATUS_TRANSITION"
    old = await admin.post(admin.h(f"/reservations/{res['id']}/confirm"), {"version": stale})
    assert old.status_code == 409 and error_code(old) == "VERSION_CONFLICT"
    # No-show is impossible before the arrival date.
    future = (await admin.post(admin.h("/reservations"), booking(hotel, 5, 6))).json()
    r = await admin.post(admin.h(f"/reservations/{future['id']}/no-show"), {"version": future["version"]})
    assert error_code(r) == "NO_SHOW_BEFORE_ARRIVAL"


async def test_changing_dates_keeps_booked_prices(admin: Api, hotel):
    res = (await admin.post(admin.h("/reservations"), booking(hotel, 0, 2))).json()
    rt = (await admin.get(admin.h(f"/room-types/{hotel['rt']}"))).json()
    await admin.patch(
        admin.h(f"/room-types/{hotel['rt']}"), {"version": rt["version"], "base_price": "80.00"}
    )
    rr = res["rooms"][0]["id"]
    r = await admin.post(
        admin.h(f"/reservations/{res['id']}/rooms/{rr}/dates"),
        {"version": res["version"], "arrival": d(0), "departure": d(3)},
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert [n["price"] for n in out["rooms"][0]["nights"]] == ["50.00", "50.00", "80.00"]
    assert out["accommodation_total"] == "180.00"
    assert out["departure"] == d(3) and out["is_modified"] is True
    assert out["version"] > res["version"]


async def test_room_assignment_and_reassignment(admin: Api, hotel):
    res = (await admin.post(admin.h("/reservations"), booking(hotel, 0, 3))).json()
    rr = res["rooms"][0]["id"]
    cal = (await admin.get(admin.h("/calendar"), params={"start": d(0), "end": d(7)})).json()
    assert len(cal["unassigned"]) == 1 and cal["items"] == []
    r = await admin.post(
        admin.h(f"/reservations/{res['id']}/rooms/{rr}/assign"),
        {"version": res["version"], "room_id": hotel["r101"]},
    )
    assert r.status_code == 200 and r.json()["rooms"][0]["room_id"] == hotel["r101"]
    cal = (await admin.get(admin.h("/calendar"), params={"start": d(0), "end": d(7)})).json()
    assert cal["unassigned"] == [] and cal["items"][0]["room_id"] == hotel["r101"]
    other = (await admin.post(admin.h("/reservations"), booking(hotel, 1, 2, room=hotel["r102"]))).json()
    r2 = await admin.post(
        admin.h(f"/reservations/{res['id']}/rooms/{rr}/assign"),
        {"version": r.json()["version"], "room_id": hotel["r102"]},
    )
    assert r2.status_code == 409 and error_code(r2) == "ROOM_UNAVAILABLE"
    assert other["code"] == "R000002"


async def test_idempotent_creation(admin: Api, hotel):
    payload = booking(hotel, 0, 1)
    headers = {"Idempotency-Key": "tablet-7-abc"}
    first = await admin.post(admin.h("/reservations"), payload, headers=headers)
    retry = await admin.post(admin.h("/reservations"), payload, headers=headers)
    assert first.status_code == 201 and retry.status_code == 200
    assert retry.json()["id"] == first.json()["id"]
    other = await admin.post(admin.h("/reservations"), booking(hotel, 3, 4), headers=headers)
    assert other.status_code == 409 and error_code(other) == "IDEMPOTENCY_KEY_REUSED"
    # Two simultaneous retries of a new request create exactly one reservation.
    apis = await _parallel_clients(admin, 3)
    try:
        payload = booking(hotel, 6, 7)
        rs = await asyncio.gather(
            *[a.post(a.h("/reservations"), payload, headers={"Idempotency-Key": "k2"}) for a in apis]
        )
    finally:
        for a in apis:
            await a.client.aclose()
    assert len({r.json()["id"] for r in rs}) == 1, [r.text for r in rs]


async def test_occupancy_limits(admin: Api, hotel):
    r = await admin.post(admin.h("/reservations"), booking(hotel, 0, 1, adults=4))
    assert r.status_code == 422 and error_code(r) == "OCCUPANCY_EXCEEDED"
    r = await admin.post(admin.h("/reservations"), {**booking(hotel, 2, 1)})
    assert r.status_code == 422


async def test_guest_duplicates_and_sensitive_data(admin: Api, hotel, user_factory):
    g = await admin.post(
        admin.h("/guests"),
        {
            "first_name": "Sophea",
            "last_name": "Chan",
            "email": "sophea@example.com",
            "phone": "+855 12 345 678",
            "id_document_type": "passport",
            "id_document_number": "N1234567",
        },
    )
    assert g.status_code == 201, g.text
    assert g.json()["id_document_number"] == "N1234567"
    dups = (
        await admin.get(
            admin.h("/guests/duplicates"),
            params={"first_name": "Sopheа", "last_name": "Chan", "phone": "012345678"},
        )
    ).json()
    assert dups and dups[0]["guest"]["id"] == g.json()["id"]
    found = (await admin.get(admin.h("/guests"), params={"q": "sophea"})).json()
    assert found["total"] == 1

    clerk = await user_factory("receptionist")
    seen = (await clerk.get(clerk.h(f"/guests/{g.json()['id']}"))).json()
    assert seen["has_id_document"] is True and seen["id_document_number"] is None
    r = await clerk.patch(
        clerk.h(f"/guests/{g.json()['id']}"), {"version": seen["version"], "id_document_number": "X"}
    )
    assert r.status_code == 422 and error_code(r) == "SENSITIVE_FIELDS_FORBIDDEN"
    async with sessionmaker()() as db:
        raw = await db.scalar(text("SELECT id_document_number FROM guests"))
    assert b"N1234567" not in raw  # encrypted at rest


async def test_reservations_are_isolated_between_hotels(admin: Api, hotel):
    res = (await admin.post(admin.h("/reservations"), booking(hotel, 0, 1))).json()
    other = (await admin.post("/api/v1/hotels", {"code": "OTHER", "name": "Other"})).json()
    r = await admin.get(f"/api/v1/hotels/{other['id']}/reservations/{res['id']}")
    assert r.status_code == 404


async def test_move_stay_room_and_dates_atomically(admin: Api, hotel):
    """Calendar drag-and-drop: one call changes room and dates, or nothing at all."""
    res = (await admin.post(admin.h("/reservations"), booking(hotel, 0, 2, room=hotel["r101"]))).json()
    rr = res["rooms"][0]["id"]
    blocker = (await admin.post(admin.h("/reservations"), booking(hotel, 5, 6, room=hotel["r102"]))).json()
    # Target conflicts on room 102 → nothing changes (not even the dates).
    r = await admin.post(
        admin.h(f"/reservations/{res['id']}/rooms/{rr}/move"),
        {"version": res["version"], "room_id": hotel["r102"], "arrival": d(4), "departure": d(6)},
    )
    assert r.status_code == 409 and error_code(r) == "ROOM_UNAVAILABLE"
    same = (await admin.get(admin.h(f"/reservations/{res['id']}"))).json()
    assert (same["arrival"], same["rooms"][0]["room_id"]) == (d(0), hotel["r101"])
    r = await admin.post(
        admin.h(f"/reservations/{res['id']}/rooms/{rr}/move"),
        {"version": res["version"], "room_id": hotel["r102"], "arrival": d(1), "departure": d(3)},
    )
    assert r.status_code == 200, r.text
    moved = r.json()
    assert (moved["arrival"], moved["departure"], moved["rooms"][0]["room_id"]) == (d(1), d(3), hotel["r102"])
    events = (await admin.get(admin.h(f"/reservations/{res['id']}/events"))).json()
    assert [e["action"] for e in events][-2:] == ["room_assigned", "dates_changed"]
    assert events[-1]["user_name"] == "Admin"
    assert blocker["code"] == "R000002"


async def test_available_rooms_and_list_filters(admin: Api, hotel):
    res = (await admin.post(admin.h("/reservations"), booking(hotel, 0, 2, room=hotel["r101"]))).json()
    free = (await admin.get(admin.h("/available-rooms"), params={"start": d(1), "end": d(3)})).json()
    assert [r["number"] for r in free] == ["102"]
    # The stay being edited does not hide its own room.
    own = (
        await admin.get(
            admin.h("/available-rooms"),
            params={"start": d(1), "end": d(3), "ignore_reservation_room": res["rooms"][0]["id"]},
        )
    ).json()
    assert [r["number"] for r in own] == ["101", "102"]
    arrivals = (await admin.get(admin.h("/reservations"), params={"arrival": d(0)})).json()
    assert arrivals["total"] == 1 and arrivals["items"][0]["room_numbers"] == ["101"]
    by_guest = (await admin.get(admin.h("/reservations"), params={"guest_id": res["booker"]["id"]})).json()
    assert by_guest["total"] == 1
    assert (await admin.get(admin.h("/reservations"), params={"departure": d(5)})).json()["total"] == 0


async def test_resaving_identity_document_is_not_a_change(admin: Api):
    g = (
        await admin.post(
            admin.h("/guests"), {"first_name": "Vanna", "last_name": "Keo", "id_document_number": "P999"}
        )
    ).json()
    r = await admin.patch(
        admin.h(f"/guests/{g['id']}"), {"version": g["version"], "id_document_number": "P999"}
    )
    assert r.status_code == 200 and r.json()["version"] == g["version"]
    logs = (await admin.get(admin.h("/audit-logs"), params={"entity_type": "guest"})).json()["items"]
    assert [e["action"] for e in logs] == ["guest.create"]
