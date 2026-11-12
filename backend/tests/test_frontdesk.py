"""Phase 5 — front desk: check-in, check-out, early departure, room moves,
daily views, housekeeping status after departure."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from app.core.db import sessionmaker
from tests.conftest import Api, error_code


def today() -> date:
    return datetime.now(ZoneInfo("Asia/Phnom_Penh")).date()


def d(offset: int) -> str:
    return (today() + timedelta(days=offset)).isoformat()


@pytest.fixture
async def hotel(admin: Api) -> dict:
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
            },
        )
    ).json()
    rooms = (
        await admin.post(admin.h("/rooms/bulk"), {"room_type_id": rt["id"], "start": 101, "end": 103})
    ).json()
    return {"rt": rt["id"], "rooms": {r["number"]: r["id"] for r in rooms}}


async def book(api: Api, hotel: dict, arrival: int, departure: int, room: str | None = None, **extra) -> dict:
    r = await api.post(
        api.h("/reservations"),
        {
            "arrival": d(arrival),
            "departure": d(departure),
            "guest": {"first_name": "Dara", "last_name": "Sok"},
            "rooms": [
                {
                    "room_type_id": hotel["rt"],
                    "room_id": hotel["rooms"][room] if room else None,
                    "adults": 2,
                }
            ],
            "override_restrictions": True,
            **extra,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


async def check_in(api: Api, res: dict, **body) -> object:
    return await api.post(api.h(f"/reservations/{res['id']}/check-in"), {"version": res["version"], **body})


async def check_out(api: Api, res: dict, **body) -> object:
    return await api.post(api.h(f"/reservations/{res['id']}/check-out"), {"version": res["version"], **body})


async def pay(api: Api, res: dict, amount: str, **body) -> dict:
    r = await api.post(
        api.h(f"/reservations/{res['id']}/payments"), {"method": "cash", "amount": amount, **body}
    )
    assert r.status_code == 201, r.text
    return r.json()


async def fresh(api: Api, res: dict) -> dict:
    return (await api.get(api.h(f"/reservations/{res['id']}"))).json()


async def set_status(api: Api, hotel: dict, number: str, status: str) -> None:
    r = await api.post(api.h(f"/rooms/{hotel['rooms'][number]}/housekeeping-status"), {"status": status})
    assert r.status_code == 200, r.text


async def test_check_in_rules(admin: Api, hotel):
    res = await book(admin, hotel, 0, 2)
    r = await check_in(admin, res)
    assert r.status_code == 409 and error_code(r) == "ROOM_NOT_ASSIGNED"

    rr = res["rooms"][0]["id"]
    res = (
        await admin.post(
            admin.h(f"/reservations/{res['id']}/rooms/{rr}/assign"),
            {"version": res["version"], "room_id": hotel["rooms"]["101"]},
        )
    ).json()
    await set_status(admin, hotel, "101", "dirty")
    r = await check_in(admin, res)
    assert r.status_code == 409 and error_code(r) == "ROOM_NOT_READY"
    assert r.json()["error"]["params"] == {"room": "101", "status": "dirty"}

    r = await check_in(admin, res, ignore_room_status=True)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "checked_in" and body["rooms"][0]["checked_in_at"]
    events = (await admin.get(admin.h(f"/reservations/{res['id']}/events"))).json()
    assert events[-1]["action"] == "checked_in"
    assert events[-1]["details"]["rooms"] == ["101"] and events[-1]["details"]["room_not_ready"] == ["101"]

    # Checking in twice, or a future arrival, is refused.
    assert error_code(await check_in(admin, body)) == "NOTHING_TO_CHECK_IN"
    future = await book(admin, hotel, 3, 5, room="102")
    r = await check_in(admin, future)
    assert r.status_code == 409 and error_code(r) == "CHECK_IN_TOO_EARLY"
    # Cancelled reservations cannot be checked in.
    other = await book(admin, hotel, 0, 1, room="103")
    other = (
        await admin.post(
            admin.h(f"/reservations/{other['id']}/cancel"),
            {"version": other["version"], "reason": "test", "waive_fee": True},
        )
    ).json()
    assert error_code(await check_in(admin, other)) == "INVALID_STATUS_TRANSITION"


async def test_pending_walk_in_and_undo_check_in(admin: Api, hotel):
    res = await book(admin, hotel, 0, 1, room="101", status="pending")
    r = await check_in(admin, res)
    assert r.status_code == 200 and r.json()["status"] == "checked_in"
    res = r.json()
    r = await admin.post(
        admin.h(f"/reservations/{res['id']}/undo-check-in"),
        {"version": res["version"], "reservation_room_id": res["rooms"][0]["id"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "confirmed" and r.json()["rooms"][0]["checked_in_at"] is None


async def test_late_arrival_and_ended_stays(admin: Api, hotel):
    late = await book(admin, hotel, -1, 2, room="101")
    r = await check_in(admin, late)
    assert r.status_code == 200, r.text  # arrived a day late: remaining nights still to come
    ended = await book(admin, hotel, -2, 0, room="102")
    assert error_code(await check_in(admin, ended)) == "NOTHING_TO_CHECK_IN"
    r = await check_in(admin, ended, reservation_room_ids=[ended["rooms"][0]["id"]])
    assert error_code(r) == "STAY_ALREADY_ENDED"


async def test_room_still_occupied_blocks_check_in(admin: Api, hotel):
    # Guest A in 101 since yesterday, due out today, still in the room.
    a = await book(admin, hotel, -1, 0, room="101")
    async with sessionmaker()() as db:
        # Check A in yesterday (the API only checks in while nights remain).
        await db.execute(
            text(
                "UPDATE reservation_rooms SET checked_in_at = now() - interval '1 day' "
                "WHERE reservation_id = :r"
            ),
            {"r": a["id"]},
        )
        await db.execute(text("UPDATE reservations SET status = 'checked_in' WHERE id = :r"), {"r": a["id"]})
        await db.commit()
    b = await book(admin, hotel, 0, 2, room="101")
    r = await check_in(admin, b)
    assert r.status_code == 409 and error_code(r) == "ROOM_STILL_OCCUPIED"
    assert r.json()["error"]["params"] == {"room": "101", "reservation": a["code"]}

    # A is overdue on the front desk; settle and check out -> room becomes dirty.
    desk = (await admin.get(admin.h("/front-desk"))).json()
    due = [x for x in desk["departures"] if x["code"] == a["code"]]
    assert due and "overdue" not in due[0]["flags"]  # departure is today, not overdue
    a = await fresh(admin, a)
    await pay(admin, a, a["balance"])
    a = await fresh(admin, a)
    r = await check_out(admin, a)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "checked_out"
    board = {x["number"]: x for x in (await admin.get(admin.h("/room-board"))).json()}
    assert board["101"]["housekeeping_status"] == "dirty" and board["101"]["occupant"] is None
    assert board["101"]["arriving"]["code"] == b["code"]

    r = await check_in(admin, await fresh(admin, b))
    assert error_code(r) == "ROOM_NOT_READY"
    await set_status(admin, hotel, "101", "clean")
    r = await check_in(admin, await fresh(admin, b))
    assert r.status_code == 200, r.text


async def test_check_out_requires_a_settled_balance(admin: Api, hotel, user_factory):
    res = await book(admin, hotel, 0, 2, room="101")
    res = (await check_in(admin, res)).json()
    assert res["balance"] == "100.00"

    r = await check_out(admin, res)
    # Leaving on the arrival day of a 2-night stay is an early departure first.
    assert r.status_code == 409 and error_code(r) == "EARLY_DEPARTURE"
    assert r.json()["error"]["params"] == {"departure": d(2), "nights": 1}

    r = await check_out(admin, res, shorten_stay=True)
    assert r.status_code == 409 and error_code(r) == "BALANCE_DUE"
    # The failed attempt changed nothing.
    res = await fresh(admin, res)
    assert res["departure"] == d(2) and res["grand_total"] == "100.00"

    receptionist = await user_factory("receptionist")
    r = await check_out(receptionist, res, shorten_stay=True, allow_open_balance=True)
    assert r.status_code == 403  # leaving money owed needs folio.adjust

    await pay(admin, res, "50.00")
    res = await fresh(admin, res)
    r = await check_out(receptionist, res, shorten_stay=True)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "checked_out"
    assert out["departure"] == d(1) and out["grand_total"] == "50.00" and out["balance"] == "0.00"
    events = (await admin.get(admin.h(f"/reservations/{res['id']}/events"))).json()
    assert events[-1]["action"] == "checked_out"
    assert list(events[-1]["details"]["early_departure"].values())[0]["nights"] == 1

    # The released night can be sold again: room 101 is free tonight.
    again = await book(admin, hotel, 1, 2, room="101")
    assert again["status"] == "confirmed"


async def test_credit_balance_needs_confirmation(admin: Api, hotel):
    res = await book(admin, hotel, -1, 1, room="101")
    res = (await check_in(admin, res)).json()
    await pay(admin, res, "80.00")  # leaving today: one night (50.00) is kept
    res = await fresh(admin, res)
    r = await check_out(admin, res, shorten_stay=True)
    assert error_code(r) == "CREDIT_BALANCE" and r.json()["error"]["params"]["balance"] == "30.00"
    r = await admin.post(
        admin.h(f"/reservations/{res['id']}/payments"),
        {"kind": "refund", "method": "cash", "amount": "30.00"},
    )
    assert r.status_code == 201
    r = await check_out(admin, await fresh(admin, res), shorten_stay=True)
    assert r.status_code == 200 and r.json()["balance"] == "0.00"


async def test_in_house_room_move_splits_the_stay(admin: Api, hotel):
    res = await book(admin, hotel, -2, 2, room="101")
    res = (await check_in(admin, res)).json()
    total = res["grand_total"]
    rr = res["rooms"][0]["id"]
    # The calendar's room reassignment refuses in-house guests.
    r = await admin.post(
        admin.h(f"/reservations/{res['id']}/rooms/{rr}/assign"),
        {"version": res["version"], "room_id": hotel["rooms"]["102"]},
    )
    assert error_code(r) == "GUEST_IN_HOUSE"

    r = await admin.post(
        admin.h(f"/reservations/{res['id']}/rooms/{rr}/room-move"),
        {"version": res["version"], "room_id": hotel["rooms"]["102"], "reason": "Air conditioning"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    stays = sorted(body["rooms"], key=lambda s: s["arrival"])
    assert [(s["room_id"], s["arrival"], s["departure"]) for s in stays] == [
        (hotel["rooms"]["101"], d(-2), d(0)),
        (hotel["rooms"]["102"], d(0), d(2)),
    ]
    assert stays[0]["checked_out_at"] and stays[1]["checked_in_at"] and not stays[1]["checked_out_at"]
    assert body["grand_total"] == total and body["status"] == "checked_in"
    board = {x["number"]: x for x in (await admin.get(admin.h("/room-board"))).json()}
    assert board["101"]["housekeeping_status"] == "dirty" and board["101"]["occupant"] is None
    assert board["102"]["occupant"]["code"] == res["code"]
    # Room 101 is free from tonight.
    await book(admin, hotel, 0, 1, room="101")
    # And the move cannot target a room occupied tonight.
    r = await admin.post(
        admin.h(f"/reservations/{res['id']}/rooms/{stays[1]['id']}/room-move"),
        {"version": body["version"], "room_id": hotel["rooms"]["101"], "ignore_room_status": True},
    )
    assert r.status_code == 409 and error_code(r) == "ROOM_UNAVAILABLE"


async def test_front_desk_lists(admin: Api, hotel):
    arriving = await book(admin, hotel, 0, 2, room="101")
    late = await book(admin, hotel, -1, 2, room="102")
    tomorrow = await book(admin, hotel, 1, 2, room="103")
    desk = (await admin.get(admin.h("/front-desk"))).json()
    assert desk["is_today"] is True
    codes = {r["code"]: r for r in desk["arrivals"]}
    assert set(codes) == {arriving["code"], late["code"]}
    assert codes[late["code"]]["flags"] == ["late_arrival"] and codes[arriving["code"]]["flags"] == []
    assert desk["in_house"] == [] and desk["departures"] == []

    await check_in(admin, arriving)
    desk = (await admin.get(admin.h("/front-desk"))).json()
    assert [r["code"] for r in desk["in_house"]] == [arriving["code"]]
    planned = (await admin.get(admin.h("/front-desk"), params={"day": d(1)})).json()
    assert planned["is_today"] is False
    assert tomorrow["code"] in {r["code"] for r in planned["arrivals"]}


async def test_housekeeping_status_needs_permission(admin: Api, hotel, user_factory):
    receptionist = await user_factory("receptionist")
    r = await receptionist.post(
        receptionist.h(f"/rooms/{hotel['rooms']['101']}/housekeeping-status"), {"status": "dirty"}
    )
    assert r.status_code == 403
    housekeeper = await user_factory("housekeeping")
    r = await housekeeper.post(
        housekeeper.h(f"/rooms/{hotel['rooms']['101']}/housekeeping-status"), {"status": "dirty"}
    )
    assert r.status_code == 200 and r.json()["housekeeping_status"] == "dirty"
    logs = (await admin.get(admin.h("/audit-logs"), params={"entity_type": "room"})).json()
    assert logs["items"][0]["action"] == "room.housekeeping_status"
