"""Two-factor authentication: recovery codes, TOTP codes accepted once, and
roles that require two-factor (their holders may only set it up until then)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time

import pyotp
import pytest
import websockets
from sqlalchemy import text
from websockets.exceptions import ConnectionClosed

from app.core.db import owner_sessionmaker
from tests.conftest import Api, error_code, new_client, role_id
from tests.test_realtime import _token, server  # noqa: F401  (fixture)
from tests.test_security import PUBLIC, call, concrete, operations

PASSWORD = "Str0ng-Passw0rd"
SETUP_ROUTES = {
    ("GET", "/api/v1/auth/me"),
    ("PATCH", "/api/v1/auth/me"),
    ("POST", "/api/v1/auth/logout"),
    ("POST", "/api/v1/auth/me/totp/setup"),
    ("POST", "/api/v1/auth/me/totp/enable"),
}


async def enable_totp(api: Api) -> tuple[pyotp.TOTP, list[str]]:
    setup = (await api.post("/api/v1/auth/me/totp/setup")).json()
    assert setup["qr_svg"].startswith("data:image/svg+xml")
    totp = pyotp.TOTP(setup["secret"])
    r = await api.post("/api/v1/auth/me/totp/enable", {"code": totp.now()})
    assert r.status_code == 200, r.text
    return totp, r.json()["codes"]


async def login(email: str, **extra) -> tuple[Api, object]:
    client = new_client()
    api = Api(client)
    return api, await api.login(email, PASSWORD, **extra)


async def test_recovery_codes(admin: Api, user_factory):
    clerk = await user_factory("receptionist", "clerk@example.com")
    totp, codes = await enable_totp(clerk)
    assert len(codes) == len(set(codes)) == 10
    assert all(re.fullmatch(r"[2-9a-hjkmnp-z]{5}-[2-9a-hjkmnp-z]{5}", c) for c in codes)
    assert (await clerk.get("/api/v1/auth/me")).json()["recovery_codes_left"] == 10

    # Only keyed hashes are stored: not the code, not its plain SHA-256.
    async with owner_sessionmaker()() as db:
        stored = set(await db.scalars(text("SELECT code_hash FROM user_recovery_codes")))
    assert len(stored) == 10
    assert not stored & {c for c in codes} and not stored & {
        hashlib.sha256(c.encode()).hexdigest() for c in codes
    }

    # A lost phone: a recovery code, typed in capitals and without the dash.
    api, r = await login("clerk@example.com", recovery_code=codes[3].upper().replace("-", " "))
    assert r.status_code == 200, r.text
    assert (await api.get("/api/v1/auth/me")).json()["recovery_codes_left"] == 9
    await api.client.aclose()
    # Each code works once.
    api, r = await login("clerk@example.com", recovery_code=codes[3])
    assert r.status_code == 401 and error_code(r) == "RECOVERY_CODE_INVALID"
    await api.client.aclose()
    history = (await admin.get(admin.h("/login-events"))).json()["items"]
    assert any(e["success"] and e["reason"] == "recovery_code" for e in history)
    assert any(not e["success"] and e["reason"] == "bad_recovery_code" for e in history)

    # New codes need the password; the old ones stop working.
    r = await clerk.post("/api/v1/auth/me/recovery-codes", {"password": "wrong"})
    assert r.status_code == 422 and error_code(r) == "INVALID_CURRENT_PASSWORD"
    r = await clerk.post("/api/v1/auth/me/recovery-codes", {"password": PASSWORD})
    assert r.status_code == 200 and len(set(r.json()["codes"]) - set(codes)) == 10
    api, r = await login("clerk@example.com", recovery_code=codes[0])
    assert error_code(r) == "RECOVERY_CODE_INVALID"
    await api.client.aclose()

    # Turning two-factor off (or an administrator's reset) removes them.
    assert (await clerk.post("/api/v1/auth/me/totp/disable", {"password": PASSWORD})).status_code == 204
    async with owner_sessionmaker()() as db:
        assert await db.scalar(text("SELECT count(*) FROM user_recovery_codes")) == 0
    assert (await clerk.get("/api/v1/auth/me")).json()["recovery_codes_left"] is None


async def test_a_totp_code_is_accepted_once(user_factory):
    clerk = await user_factory("receptionist", "clerk@example.com")
    totp, _ = await enable_totp(clerk)  # consumes the current time step
    api, r = await login("clerk@example.com", totp_code=totp.now())
    assert r.status_code == 401 and error_code(r) == "TOTP_INVALID"
    await api.client.aclose()
    following = totp.at(time.time() + 30)
    api, r = await login("clerk@example.com", totp_code=following)
    assert r.status_code == 200
    await api.client.aclose()
    api, r = await login("clerk@example.com", totp_code=following)  # replayed
    assert r.status_code == 401 and error_code(r) == "TOTP_INVALID"
    await api.client.aclose()


async def test_a_role_can_require_two_factor(admin: Api, user_factory):
    receptionist = await role_id(admin, "receptionist")
    role = next(r for r in (await admin.get(admin.h("/roles"))).json() if r["id"] == receptionist)
    assert role["is_system"] and role["require_2fa"] is False
    # A system role's name and permissions stay fixed; its two-factor policy may change.
    r = await admin.patch(admin.h(f"/roles/{receptionist}"), {"version": role["version"], "name": "Desk"})
    assert r.status_code == 403 and error_code(r) == "SYSTEM_ROLE_READONLY"
    r = await admin.patch(
        admin.h(f"/roles/{receptionist}"), {"version": role["version"], "require_2fa": True}
    )
    assert r.status_code == 200 and r.json()["require_2fa"] is True

    clerk = await user_factory("receptionist", "clerk@example.com")  # signs in with the password
    me = (await clerk.get("/api/v1/auth/me")).json()
    assert me["two_factor_required"] and me["two_factor_setup_required"]
    r = await clerk.get(clerk.h("/reservations"))
    assert r.status_code == 403 and error_code(r) == "TWO_FACTOR_SETUP_REQUIRED"
    # Every other operation of the API is refused the same way.
    unexpected = []
    for method, path, params in operations():
        if (method, path) in PUBLIC or (method, path) in SETUP_ROUTES:
            continue
        r = await call(clerk.client, method, concrete(path, params, clerk.hotel_id or ""))
        if r.status_code != 403 or error_code(r) != "TWO_FACTOR_SETUP_REQUIRED":
            unexpected.append((method, path, r.status_code))
    assert unexpected == []

    # Setting it up opens the hotel; it cannot be turned off while the role requires it.
    await enable_totp(clerk)
    assert (await clerk.get(clerk.h("/reservations"))).status_code == 200
    assert (await clerk.get("/api/v1/auth/me")).json()["two_factor_setup_required"] is False
    r = await clerk.post("/api/v1/auth/me/totp/disable", {"password": PASSWORD})
    assert r.status_code == 403 and error_code(r) == "TWO_FACTOR_REQUIRED_BY_ROLE"

    # Custom roles carry the setting from their creation.
    r = await admin.post(
        admin.h("/roles"),
        {
            "code": "night_auditor",
            "name": "Night auditor",
            "permissions": ["nightaudit.run"],
            "require_2fa": True,
        },
    )
    assert r.status_code == 201 and r.json()["require_2fa"] is True
    logs = (await admin.get(admin.h("/audit-logs"), params={"entity_type": "role"})).json()["items"]
    assert any(e["action"] == "role.update" and "require_2fa" in (e["changes"] or {}) for e in logs)


@pytest.mark.usefixtures("installation")
async def test_no_live_updates_before_two_factor_is_set_up(server, admin: Api, user_factory):  # noqa: F811
    receptionist = await role_id(admin, "receptionist")
    role = next(r for r in (await admin.get(admin.h("/roles"))).json() if r["id"] == receptionist)
    await admin.patch(admin.h(f"/roles/{receptionist}"), {"version": role["version"], "require_2fa": True})
    await user_factory("receptionist", "clerk@example.com")
    token = await _token(server, "clerk@example.com", PASSWORD)
    ws = await websockets.connect(f"ws://{server}/api/v1/ws")
    await ws.send(json.dumps({"type": "auth", "token": token}))
    with pytest.raises(ConnectionClosed) as exc:
        await asyncio.wait_for(ws.recv(), 5)
    assert exc.value.rcvd.code == 4403
