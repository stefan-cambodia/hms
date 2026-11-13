"""Rooms taken out of service keep counting in the periods they were part of
the hotel (room_service_periods, kept by a trigger on rooms)."""

from __future__ import annotations

import importlib.util
from datetime import timedelta
from pathlib import Path

from sqlalchemy import text

from app.core.db import owner_sessionmaker
from tests.conftest import Api, error_code
from tests.test_reports import book, hotel, performance, today  # noqa: F401  (fixture)

MIGRATION_0014 = (
    Path(__file__).resolve().parents[1] / "migrations/versions/20261114_0014_room_service_periods.py"
)


async def periods(room_id: str) -> list[tuple]:
    async with owner_sessionmaker()() as db:
        rows = await db.execute(
            text(
                "SELECT lower(period), upper(period) FROM room_service_periods WHERE room_id = :r ORDER BY 1"
            ),
            {"r": room_id},
        )
        return [tuple(r) for r in rows]


async def set_active(admin: Api, room_id: str, active: bool):
    room = (await admin.get(admin.h(f"/rooms/{room_id}"))).json()
    return await admin.patch(admin.h(f"/rooms/{room_id}"), {"version": room["version"], "is_active": active})


async def open_since(days: int) -> None:
    """The hotel's rooms have been in service for `days` nights."""
    async with owner_sessionmaker()() as db:
        await db.execute(
            text("UPDATE room_service_periods SET period = daterange(CAST(:d AS date), NULL)"),
            {"d": today() - timedelta(days=days)},
        )
        await db.commit()


async def test_a_room_out_of_service_still_counts_in_the_past(admin: Api, hotel):  # noqa: F811
    rooms = hotel["rooms"]  # 5 rooms
    await open_since(40)
    assert (await performance(admin, -30, 0))["totals"]["rooms"] == 150

    r = await set_active(admin, rooms["103"], False)
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert await periods(rooms["103"]) == [(today() - timedelta(days=40), today())]
    assert (await performance(admin, -30, 0))["totals"]["rooms"] == 150  # the past is unchanged
    nights = await performance(admin, 0, 7)
    assert (nights["totals"]["rooms"], nights["totals"]["available"]) == (28, 28)  # 4 rooms from tonight

    # Back in service the same day: one continuous period, as if nothing happened.
    assert (await set_active(admin, rooms["103"], True)).status_code == 200
    assert await periods(rooms["103"]) == [(today() - timedelta(days=40), None)]
    assert (await performance(admin, 0, 7))["totals"]["rooms"] == 35


async def test_a_gap_out_of_service_is_kept(admin: Api, hotel):  # noqa: F811
    room = hotel["rooms"]["201"]
    await open_since(40)
    assert (await set_active(admin, room, False)).status_code == 200
    # It was in fact out of service from ten days ago (as if done then).
    async with owner_sessionmaker()() as db:
        await db.execute(
            text(
                "UPDATE room_service_periods SET period = daterange(lower(period), CAST(:d AS date))"
                " WHERE room_id = :r"
            ),
            {"d": today() - timedelta(days=10), "r": room},
        )
        await db.commit()
    assert (await set_active(admin, room, True)).status_code == 200
    assert await periods(room) == [
        (today() - timedelta(days=40), today() - timedelta(days=10)),
        (today(), None),
    ]
    rep = await performance(admin, -15, 0)
    assert rep["totals"]["rooms"] == 5 * 15 - 10
    by_night = {x["date"]: x["available"] for x in rep["daily"]}
    assert by_night[(today() - timedelta(days=11)).isoformat()] == 5
    assert by_night[(today() - timedelta(days=10)).isoformat()] == 4


async def test_a_new_room_counts_from_tonight(admin: Api, hotel):  # noqa: F811
    r = await admin.post(admin.h("/rooms"), {"room_type_id": hotel["a"], "number": "199"})
    assert r.status_code == 201, r.text
    room = r.json()["id"]
    assert await periods(room) == [(today(), None)]
    # Created by mistake and switched off the same day: it never counted.
    assert (await set_active(admin, room, False)).status_code == 200
    assert await periods(room) == []
    # Created out of service: no period until it is switched on.
    r = await admin.post(admin.h("/rooms"), {"room_type_id": hotel["a"], "number": "198", "is_active": False})
    assert r.status_code == 201 and await periods(r.json()["id"]) == []


async def test_a_room_with_stays_cannot_be_taken_out_of_service(admin: Api, hotel):  # noqa: F811
    rooms = hotel["rooms"]
    future = await book(admin, hotel["a"], 2, 4, room_id=rooms["102"])
    await book(admin, hotel["a"], -1, 1, room_id=rooms["101"])  # in the room tonight
    for number in ("101", "102"):
        r = await set_active(admin, rooms[number], False)
        assert r.status_code == 409 and error_code(r) == "ROOM_HAS_STAYS", number
        assert r.json()["error"]["params"] == {"count": 1}
    # Once the guest is moved elsewhere (here: the booking cancelled), it can.
    r = await admin.post(
        admin.h(f"/reservations/{future['id']}/cancel"), {"version": future["version"], "reason": "Moved"}
    )
    assert r.status_code == 200, r.text
    assert (await set_active(admin, rooms["102"], False)).status_code == 200
    # Past stays never prevent it.
    await book(admin, hotel["b"], -5, -3, room_id=rooms["202"])
    assert (await set_active(admin, rooms["202"], False)).status_code == 200


async def test_existing_rooms_get_their_history_from_the_audit_trail(admin: Api, hotel):  # noqa: F811
    """Migration 0014: rooms in service from their creation; a room out of
    service today until its last deactivation recorded in the audit trail."""
    spec = importlib.util.spec_from_file_location("m0014", MIGRATION_0014)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    room = hotel["rooms"]["103"]
    async with owner_sessionmaker()() as db:  # as before the migration
        await db.execute(text("UPDATE rooms SET is_active = false WHERE id = :r"), {"r": room})
        await db.execute(  # deactivated five days ago, a month after the rooms were created
            text(
                "INSERT INTO audit_logs"
                " (at, organization_id, hotel_id, source, action, entity_type, entity_id, changes)"
                " SELECT now() - interval '5 days', h.organization_id, h.id,"
                " 'api', 'room.update', 'room', :r,"
                " CAST('{\"is_active\": [true, false]}' AS jsonb) FROM hotels h"
            ),
            {"r": room},
        )
        await db.execute(text("UPDATE rooms SET created_at = now() - interval '30 days'"))
        await db.execute(text("DELETE FROM room_service_periods"))
        await db.execute(text(migration.BACKFILL))
        await db.commit()
    assert await periods(hotel["rooms"]["101"]) == [(today() - timedelta(days=30), None)]
    assert await periods(room) == [(today() - timedelta(days=30), today() - timedelta(days=5))]
    rep = await performance(admin, -10, 0)
    assert rep["totals"]["rooms"] == 5 * 10 - 5
