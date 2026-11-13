from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.db import owner_sessionmaker, sessionmaker
from tests.conftest import Api, error_code, make_user, new_client, role_id


async def test_permissions_enforced_server_side(user_factory):
    housekeeper = await user_factory("housekeeping")
    assert (await housekeeper.get(housekeeper.h(""))).status_code == 200  # hotel.view
    hotel = (await housekeeper.get(housekeeper.h(""))).json()
    r = await housekeeper.patch(housekeeper.h(""), {"version": hotel["version"], "name": "Pwned"})
    assert r.status_code == 403 and error_code(r) == "PERMISSION_DENIED"
    assert r.json()["error"]["params"]["permission"] == "config.hotel.manage"
    r = await housekeeper.post(housekeeper.h("/buildings"), {"code": "X", "name": "X"})
    assert r.status_code == 403
    assert (await housekeeper.get(housekeeper.h("/users"))).status_code == 403


async def test_hotels_are_isolated(admin: Api):
    other = await admin.post("/api/v1/hotels", {"code": "OTHER", "name": "Other Hotel"})
    assert other.status_code == 201, other.text
    other_id = other.json()["id"]
    # Superadmin sees both; a hotel-A receptionist must not see hotel B at all.
    await make_user(admin, "clerk@example.com", "receptionist")
    async with new_client() as client:
        clerk = Api(client, admin.hotel_id)
        await clerk.login("clerk@example.com", "Str0ng-Passw0rd")
        assert [h["id"] for h in clerk.me["hotels"]] == [admin.hotel_id]
        r = await clerk.get(f"/api/v1/hotels/{other_id}/rooms")
        assert r.status_code == 404 and error_code(r) == "HOTEL_NOT_FOUND"

    # A room in hotel A cannot reference a room category of hotel B.
    rt_b = await admin.post(
        f"/api/v1/hotels/{other_id}/room-types",
        {"code": "STD", "name": {"en": "Standard"}, "base_price": "50.00"},
    )
    assert rt_b.status_code == 201
    r = await admin.post(admin.h("/rooms"), {"room_type_id": rt_b.json()["id"], "number": "101"})
    assert r.status_code == 404 and error_code(r) == "ROOM_TYPE_NOT_FOUND"


async def test_cannot_grant_permissions_you_do_not_hold(admin: Api, user_factory):
    hotel_admin = await user_factory("hotel_admin")
    r = await hotel_admin.post(
        hotel_admin.h("/roles"),
        {"code": "night", "name": "Night audit", "permissions": ["reservations.view", "backups.manage"]},
    )
    assert r.status_code == 403 and error_code(r) == "CANNOT_GRANT_PERMISSION"
    r = await hotel_admin.post(
        hotel_admin.h("/roles"),
        {"code": "night", "name": "Night audit", "permissions": ["reservations.view", "guests.view"]},
    )
    assert r.status_code == 201
    # Nor can they assign the super-admin role to someone.
    r = await hotel_admin.post(
        hotel_admin.h("/users"),
        {
            "email": "x@example.com",
            "full_name": "X",
            "password": "Str0ng-Passw0rd",
            "role_ids": [await role_id(admin, "super_admin")],
        },
    )
    assert r.status_code == 403


async def test_system_roles_are_read_only_and_custom_roles_editable(admin: Api):
    rid = await role_id(admin, "receptionist")
    r = await admin.patch(admin.h(f"/roles/{rid}"), {"version": 1, "name": "Front"})
    assert r.status_code == 403 and error_code(r) == "SYSTEM_ROLE_READONLY"
    r = await admin.post(
        admin.h("/roles"), {"code": "auditor", "name": "Auditor", "permissions": ["audit.view"]}
    )
    role = r.json()
    r = await admin.patch(
        admin.h(f"/roles/{role['id']}"),
        {"version": role["version"], "permissions": ["audit.view", "reports.view"]},
    )
    assert r.status_code == 200
    assert r.json()["permissions"] == ["audit.view", "reports.view"]
    assert r.json()["version"] == role["version"] + 1
    r = await admin.patch(admin.h(f"/roles/{role['id']}"), {"version": role["version"], "name": "Stale"})
    assert r.status_code == 409


async def test_deactivated_user_loses_access(admin: Api, user_factory):
    clerk = await user_factory("receptionist")
    users = (await admin.get(admin.h("/users"))).json()
    target = next(u for u in users if u["email"].startswith("receptionist"))
    r = await admin.patch(
        admin.h(f"/users/{target['id']}"), {"version": target["version"], "is_active": False}
    )
    assert r.status_code == 200
    assert (await clerk.get("/api/v1/auth/me")).status_code == 401


async def test_audit_log_is_append_only(admin: Api):
    await admin.post(admin.h("/buildings"), {"code": "A", "name": "Main"})
    logs = (await admin.get(admin.h("/audit-logs"))).json()
    assert logs["items"][0]["action"] == "building.create"
    # The API's role has no UPDATE/DELETE privilege on the table...
    async with sessionmaker()() as db:
        with pytest.raises(DBAPIError, match="permission denied"):
            await db.execute(text("UPDATE audit_logs SET action = 'tampered'"))
        await db.rollback()
        with pytest.raises(DBAPIError, match="permission denied"):
            await db.execute(text("DELETE FROM audit_logs"))
        await db.rollback()
    # ...and even the schema owner is stopped by the trigger.
    async with owner_sessionmaker()() as db:
        with pytest.raises(DBAPIError, match="append-only"):
            await db.execute(text("UPDATE audit_logs SET action = 'tampered'"))
        await db.rollback()
        with pytest.raises(DBAPIError, match="append-only"):
            await db.execute(text("DELETE FROM audit_logs"))
