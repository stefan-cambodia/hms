"""Phase 5 — housekeeping tasks and room status, maintenance requests with
out-of-service rooms."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

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
                "max_occupancy": 2,
                "max_adults": 2,
                "max_children": 0,
                "base_price": "50.00",
            },
        )
    ).json()
    rooms = (
        await admin.post(admin.h("/rooms/bulk"), {"room_type_id": rt["id"], "start": 101, "end": 104})
    ).json()
    return {"rt": rt["id"], "rooms": {r["number"]: r["id"] for r in rooms}}


async def book(api: Api, hotel: dict, arrival: int, departure: int, room: str) -> dict:
    r = await api.post(
        api.h("/reservations"),
        {
            "arrival": d(arrival),
            "departure": d(departure),
            "guest": {"first_name": "Vanna", "last_name": "Kim"},
            "rooms": [{"room_type_id": hotel["rt"], "room_id": hotel["rooms"][room], "adults": 2}],
            "override_restrictions": True,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


async def in_house(api: Api, hotel: dict, arrival: int, departure: int, room: str) -> dict:
    res = await book(api, hotel, arrival, departure, room)
    r = await api.post(api.h(f"/reservations/{res['id']}/check-in"), {"version": res["version"]})
    assert r.status_code == 200, r.text
    return r.json()


async def tasks(api: Api, **params) -> list[dict]:
    r = await api.get(api.h("/housekeeping/tasks"), params=params)
    assert r.status_code == 200, r.text
    return r.json()


async def board(api: Api) -> dict[str, dict]:
    return {x["number"]: x for x in (await api.get(api.h("/room-board"))).json()}


async def act(api: Api, task: dict, action: str, reason: str | None = None):
    return await api.post(api.h(f"/housekeeping/tasks/{task['id']}/{action}"), {"reason": reason})


async def test_check_out_creates_a_departure_clean(admin: Api, hotel):
    res = await in_house(admin, hotel, -1, 1, "101")
    await admin.post(admin.h(f"/reservations/{res['id']}/payments"), {"method": "cash", "amount": "50.00"})
    res = (await admin.get(admin.h(f"/reservations/{res['id']}"))).json()
    r = await admin.post(
        admin.h(f"/reservations/{res['id']}/check-out"), {"version": res["version"], "shorten_stay": True}
    )
    assert r.status_code == 200, r.text
    [task] = await tasks(admin)
    assert (task["room_number"], task["task_type"], task["status"], task["source"]) == (
        "101",
        "departure",
        "pending",
        "check_out",
    )
    assert task["priority"] == "normal" and task["room_status"] == "dirty"
    # A guest now booked into 101 tonight makes the clean urgent on the next preparation.
    await book(admin, hotel, 0, 1, "101")
    r = await admin.post(admin.h("/housekeeping/prepare"))
    assert r.status_code == 200 and r.json() == {"created": 0, "existing": 1}
    [task] = await tasks(admin)
    assert task["priority"] == "high" and task["arrival_today"] is True
    history = (await admin.get(admin.h(f"/rooms/{hotel['rooms']['101']}/status-history"))).json()
    assert [(h["from_status"], h["to_status"], h["cause"]) for h in history] == [
        ("clean", "dirty", "check_out")
    ]


async def test_task_workflow_and_permissions(admin: Api, hotel, user_factory):
    maid = await user_factory("housekeeping", "maid@example.com")
    other = await user_factory("housekeeping", "other@example.com")
    receptionist = await user_factory("receptionist")
    staff = (await admin.get(admin.h("/housekeeping/staff"))).json()
    names = [s["full_name"] for s in staff]
    assert "maid" in names and "other" in names
    assert not any(n.startswith("receptionist") for n in names)
    maid_id = next(s["id"] for s in staff if s["full_name"] == "maid")

    r = await maid.post(
        maid.h("/housekeeping/tasks"), {"room_id": hotel["rooms"]["102"], "task_type": "deep_clean"}
    )
    assert r.status_code == 403  # planning is for supervisors
    r = await admin.post(
        admin.h("/housekeeping/tasks"),
        {"room_id": hotel["rooms"]["102"], "task_type": "deep_clean", "priority": "high", "notes": "Carpet"},
    )
    assert r.status_code == 201, r.text
    task = r.json()
    r = await admin.post(
        admin.h("/housekeeping/tasks"), {"room_id": hotel["rooms"]["102"], "task_type": "deep_clean"}
    )
    assert r.status_code == 409 and error_code(r) == "TASK_EXISTS"
    # Only housekeeping staff can be assigned.
    rec_id = (await receptionist.get("/api/v1/auth/me")).json()["user"]["id"]
    r = await admin.post(admin.h("/housekeeping/tasks/assign"), {"task_ids": [task["id"]], "user_id": rec_id})
    assert r.status_code == 422 and error_code(r) == "NOT_HOUSEKEEPING_STAFF"
    r = await admin.post(
        admin.h("/housekeeping/tasks/assign"), {"task_ids": [task["id"]], "user_id": maid_id}
    )
    assert r.status_code == 200 and r.json() == {"updated": 1}

    r = await act(other, task, "start")
    assert r.status_code == 403 and error_code(r) == "TASK_ASSIGNED_TO_SOMEONE_ELSE"
    r = await act(maid, task, "start")
    assert (
        r.status_code == 200
        and r.json()["status"] == "in_progress"
        and r.json()["room_status"] == "in_progress"
    )
    r = await act(maid, task, "start")
    assert r.status_code == 409 and error_code(r) == "INVALID_TASK_TRANSITION"
    r = await act(maid, task, "complete")
    assert r.status_code == 200 and r.json()["status"] == "done" and r.json()["room_status"] == "clean"
    assert r.json()["completed_by_name"] == "maid"
    r = await act(maid, task, "inspect")
    assert r.status_code == 403  # inspection is for supervisors
    r = await act(admin, task, "inspect")
    assert (
        r.status_code == 200 and r.json()["status"] == "inspected" and r.json()["room_status"] == "inspected"
    )

    mine = await tasks(maid, assigned_to="me")
    assert [t["id"] for t in mine] == [task["id"]]
    history = (await admin.get(admin.h(f"/rooms/{hotel['rooms']['102']}/status-history"))).json()
    assert [(h["to_status"], h["cause"]) for h in reversed(history)] == [
        ("in_progress", "task"),
        ("clean", "task"),
        ("inspected", "inspection"),
    ]
    # Receptionists see the board but cannot change cleaning status.
    r = await receptionist.post(
        receptionist.h(f"/rooms/{hotel['rooms']['103']}/housekeeping-status"), {"status": "dirty"}
    )
    assert r.status_code == 403
    assert (await receptionist.get(receptionist.h("/housekeeping/tasks"))).status_code == 200


async def test_reject_skip_and_reopen(admin: Api, hotel):
    task = (
        await admin.post(
            admin.h("/housekeeping/tasks"), {"room_id": hotel["rooms"]["103"], "task_type": "touch_up"}
        )
    ).json()
    assert (await act(admin, task, "complete")).json()["room_status"] == "clean"
    r = await act(admin, task, "reject")
    assert r.status_code == 422 and error_code(r) == "REASON_REQUIRED"
    r = await act(admin, task, "reject", "Bathroom not done")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "pending" and body["room_status"] == "dirty" and "Bathroom" in body["notes"]
    assert (await act(admin, task, "start")).json()["room_status"] == "in_progress"
    r = await act(admin, task, "skip", "Guest asked not to disturb")
    assert r.status_code == 200 and r.json()["status"] == "skipped" and r.json()["room_status"] == "dirty"
    r = await act(admin, task, "reopen")
    assert r.status_code == 200 and r.json()["status"] == "pending" and r.json()["skip_reason"] is None
    r = await admin.delete(admin.h(f"/housekeeping/tasks/{task['id']}"))
    assert r.status_code == 204


async def test_daily_preparation(admin: Api, hotel):
    staying = await in_house(admin, hotel, 0, 2, "101")  # staying tonight → stayover
    await admin.post(admin.h(f"/rooms/{hotel['rooms']['102']}/housekeeping-status"), {"status": "dirty"})
    await admin.post(admin.h(f"/rooms/{hotel['rooms']['104']}/housekeeping-status"), {"status": "dirty"})
    # Room 104 is out of service: no task for it.
    r = await admin.post(
        admin.h("/maintenance-requests"),
        {
            "room_id": hotel["rooms"]["104"],
            "title": "Leaking pipe",
            "category": "plumbing",
            "out_of_service": {"start_date": d(0), "end_date": d(2)},
        },
    )
    assert r.status_code == 201, r.text

    r = await admin.post(admin.h("/housekeeping/prepare"))
    assert r.json() == {"created": 2, "existing": 0}
    got = {(t["room_number"], t["task_type"]) for t in await tasks(admin)}
    assert got == {("101", "stayover"), ("102", "departure")}
    r = await admin.post(admin.h("/housekeeping/prepare"))
    assert r.json() == {"created": 0, "existing": 2}

    # The guest of 101 leaves early today: the stayover service is dropped and
    # replaced by a departure clean.
    await admin.post(
        admin.h(f"/reservations/{staying['id']}/payments"), {"method": "cash", "amount": "50.00"}
    )
    staying = (await admin.get(admin.h(f"/reservations/{staying['id']}"))).json()
    r = await admin.post(
        admin.h(f"/reservations/{staying['id']}/check-out"),
        {"version": staying["version"], "shorten_stay": True},
    )
    assert r.status_code == 200, r.text
    by_type = {(t["room_number"], t["task_type"]): t for t in await tasks(admin)}
    assert by_type[("101", "stayover")]["status"] == "skipped"
    assert by_type[("101", "stayover")]["skip_reason"] == "guest_departed"
    assert by_type[("101", "departure")]["status"] == "pending"

    rooms = await board(admin)
    assert rooms["101"]["tasks"][0]["task_type"] in ("stayover", "departure")
    assert rooms["104"]["maintenance"] == {"open": 1, "priority": "normal"} and rooms["104"]["block"]


async def test_maintenance_takes_the_room_out_of_service(admin: Api, hotel, user_factory):
    maid = await user_factory("housekeeping")
    r = await maid.post(
        maid.h("/maintenance-requests"),
        {
            "room_id": hotel["rooms"]["103"],
            "title": "Air conditioning noisy",
            "category": "air_conditioning",
            "out_of_service": {"start_date": d(0), "end_date": d(3)},
        },
    )
    assert r.status_code == 403  # taking a room out of service needs maintenance.manage
    r = await maid.post(
        maid.h("/maintenance-requests"),
        {"room_id": hotel["rooms"]["103"], "title": "Air conditioning noisy", "category": "air_conditioning"},
    )
    assert r.status_code == 201, r.text
    req = r.json()
    assert req["number"] == "MT-000001" and req["status"] == "reported" and req["block"] is None
    assert req["reported_by_name"] and req["updates"][0]["action"] == "reported"

    r = await admin.post(
        admin.h(f"/maintenance-requests/{req['id']}/block"),
        {"version": req["version"], "start_date": d(0), "end_date": d(3)},
    )
    assert r.status_code == 200, r.text
    req = r.json()
    assert req["block"]["start_date"] == d(0) and req["block"]["end_date"] == d(3)
    # The room cannot be sold while blocked.
    r = await admin.post(
        admin.h("/reservations"),
        {
            "arrival": d(1),
            "departure": d(2),
            "guest": {"first_name": "A", "last_name": "B"},
            "rooms": [{"room_type_id": hotel["rt"], "room_id": hotel["rooms"]["103"], "adults": 1}],
        },
    )
    assert r.status_code == 409 and error_code(r) == "ROOM_UNAVAILABLE"
    # Extend it, then complete the work: the room is released and sent to housekeeping.
    r = await admin.post(
        admin.h(f"/maintenance-requests/{req['id']}/block"),
        {"version": req["version"], "start_date": d(0), "end_date": d(5)},
    )
    assert r.status_code == 200 and r.json()["block"]["end_date"] == d(5)
    req = r.json()
    r = await admin.post(
        admin.h(f"/maintenance-requests/{req['id']}/status"),
        {"version": req["version"], "status": "in_progress"},
    )
    assert r.status_code == 200 and r.json()["started_at"]
    req = r.json()
    r = await admin.post(
        admin.h(f"/maintenance-requests/{req['id']}/status"),
        {"version": req["version"], "status": "completed", "resolution": "Fan motor replaced"},
    )
    assert r.status_code == 200, r.text
    req = r.json()
    assert req["status"] == "completed" and req["resolution"] == "Fan motor replaced" and req["block"] is None
    assert [u["action"] for u in req["updates"]] == [
        "reported",
        "out_of_service",
        "out_of_service",
        "status",
        "status",
    ]
    assert req["updates"][-1]["details"]["room_released"] is True
    rooms = await board(admin)
    assert rooms["103"]["housekeeping_status"] == "dirty" and rooms["103"]["block"] is None
    assert rooms["103"]["maintenance"] is None
    assert [(t["task_type"], t["status"]) for t in rooms["103"]["tasks"]] == [("touch_up", "pending")]
    await book(admin, hotel, 0, 1, "103")  # sellable again tonight


async def test_out_of_service_conflicts_with_a_guest(admin: Api, hotel):
    await in_house(admin, hotel, 0, 2, "101")
    r = await admin.post(
        admin.h("/maintenance-requests"),
        {
            "room_id": hotel["rooms"]["101"],
            "title": "Broken window",
            "out_of_service": {"start_date": d(0), "end_date": d(1)},
        },
    )
    assert r.status_code == 409 and error_code(r) == "ROOM_UNAVAILABLE"
    # Nothing was kept from the refused request, not even its number.
    listed = (await admin.get(admin.h("/maintenance-requests"), params={"state": "all"})).json()
    assert listed["total"] == 0
    r = await admin.post(
        admin.h("/maintenance-requests"), {"room_id": hotel["rooms"]["101"], "title": "Broken window"}
    )
    assert r.json()["number"] == "MT-000001"
    # Blocking after the guest leaves is fine.
    req = r.json()
    r = await admin.post(
        admin.h(f"/maintenance-requests/{req['id']}/block"),
        {"version": req["version"], "start_date": d(2), "end_date": d(4)},
    )
    assert r.status_code == 200 and r.json()["block"]["start_date"] == d(2)


async def test_release_keeps_past_block_and_cancel(admin: Api, hotel, user_factory):
    r = await admin.post(
        admin.h("/maintenance-requests"),
        {
            "room_id": hotel["rooms"]["102"],
            "title": "Repainting",
            "category": "building",
            "priority": "low",
            "out_of_service": {"start_date": d(-2), "end_date": d(3)},
        },
    )
    req = r.json()
    r = await admin.post(admin.h(f"/maintenance-requests/{req['id']}/release"), {"version": req["version"]})
    assert r.status_code == 200 and r.json()["block"] is None
    blocks = (await admin.get(admin.h("/room-blocks"), params={"start": d(-5), "end": d(5)})).json()
    assert [(b["start_date"], b["end_date"]) for b in blocks] == [(d(-2), d(0))]  # past nights kept
    req = r.json()
    r = await admin.post(admin.h(f"/maintenance-requests/{req['id']}/release"), {"version": req["version"]})
    assert r.status_code == 409 and error_code(r) == "ROOM_NOT_BLOCKED"
    # Blocking again opens a new block; the past one stays untouched.
    r = await admin.post(
        admin.h(f"/maintenance-requests/{req['id']}/block"),
        {"version": req["version"], "start_date": d(1), "end_date": d(2)},
    )
    assert r.status_code == 200 and r.json()["block"]["start_date"] == d(1)
    blocks = (await admin.get(admin.h("/room-blocks"), params={"start": d(-5), "end": d(5)})).json()
    assert sorted((b["start_date"], b["end_date"]) for b in blocks) == [(d(-2), d(0)), (d(1), d(2))]
    req = r.json()

    receptionist = await user_factory("receptionist")
    r = await receptionist.post(
        receptionist.h(f"/maintenance-requests/{req['id']}/comments"),
        {"comment": "Guest asked when it is ready"},
    )
    assert r.status_code == 200 and r.json()["updates"][-1]["comment"] == "Guest asked when it is ready"
    r = await receptionist.post(
        receptionist.h(f"/maintenance-requests/{req['id']}/status"),
        {"version": req["version"], "status": "cancelled"},
    )
    assert r.status_code == 403
    req = (await admin.get(admin.h(f"/maintenance-requests/{req['id']}"))).json()
    r = await admin.post(
        admin.h(f"/maintenance-requests/{req['id']}/status"),
        {"version": req["version"], "status": "cancelled", "comment": "Postponed to low season"},
    )
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    req = r.json()
    r = await admin.post(
        admin.h(f"/maintenance-requests/{req['id']}/status"), {"version": req["version"], "status": "on_hold"}
    )
    assert r.status_code == 409 and error_code(r) == "INVALID_STATUS_TRANSITION"
    r = await admin.post(
        admin.h(f"/maintenance-requests/{req['id']}/status"),
        {"version": req["version"], "status": "reported"},
    )
    assert r.status_code == 200 and r.json()["status"] == "reported"
    open_list = (await admin.get(admin.h("/maintenance-requests"), params={"q": "paint"})).json()
    assert [x["number"] for x in open_list["items"]] == [req["number"]]


async def test_maintenance_assignment(admin: Api, hotel, user_factory):
    tech = await user_factory("maintenance", "tech@example.com")
    maid = await user_factory("housekeeping", "maid2@example.com")
    techs = (await admin.get(admin.h("/maintenance/technicians"))).json()
    assert "tech" in [t["full_name"] for t in techs] and "maid2" not in [t["full_name"] for t in techs]
    tech_id = next(t["id"] for t in techs if t["full_name"] == "tech")
    maid_id = (await maid.get("/api/v1/auth/me")).json()["user"]["id"]
    req = (
        await maid.post(
            maid.h("/maintenance-requests"),
            {"location": "Pool pump room", "title": "Pump stopped", "priority": "urgent"},
        )
    ).json()
    r = await admin.patch(
        admin.h(f"/maintenance-requests/{req['id']}"), {"version": req["version"], "assigned_to": maid_id}
    )
    assert r.status_code == 422 and error_code(r) == "NOT_MAINTENANCE_STAFF"
    r = await admin.patch(
        admin.h(f"/maintenance-requests/{req['id']}"), {"version": req["version"], "assigned_to": tech_id}
    )
    assert r.status_code == 200 and r.json()["assigned_to_name"] == "tech"
    mine = (await tech.get(tech.h("/maintenance-requests"), params={"assigned_to": "me"})).json()
    assert [x["number"] for x in mine["items"]] == [req["number"]]
    assert mine["items"][0]["priority"] == "urgent" and mine["items"][0]["location"] == "Pool pump room"
