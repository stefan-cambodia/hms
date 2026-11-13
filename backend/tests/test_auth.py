from __future__ import annotations

import time

import pyotp
from sqlalchemy import select, text

from app.core.db import owner_sessionmaker
from app.modules.auth.models import LoginEvent
from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD, Api, error_code, new_client


async def test_login_sets_httponly_cookie_and_returns_permissions(installation):
    async with new_client() as client:
        r = await client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        assert r.status_code == 200
        body = r.json()
        assert body["token"] is None  # browsers never see the token
        cookie = r.headers["set-cookie"]
        assert "hms_session=" in cookie and "HttpOnly" in cookie and "SameSite=strict" in cookie
        assert body["hotels"][0]["id"] == installation.hotel_id
        assert "config.rooms.manage" in body["hotels"][0]["permissions"]
        me = await client.get("/api/v1/auth/me")
        assert me.status_code == 200
        assert me.json()["user"]["email"] == ADMIN_EMAIL


async def test_wrong_password_and_unknown_email_look_identical(installation):
    async with new_client() as client:
        r1 = await client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": "nope"})
        r2 = await client.post("/api/v1/auth/login", json={"email": "ghost@example.com", "password": "nope"})
    assert r1.status_code == r2.status_code == 401
    assert error_code(r1) == error_code(r2) == "INVALID_CREDENTIALS"
    async with owner_sessionmaker()() as db:
        events = list(await db.scalars(select(LoginEvent).order_by(LoginEvent.id)))
    assert [(e.success, e.reason) for e in events] == [(False, "bad_password"), (False, "unknown_user")]


async def test_account_locks_after_repeated_failures(installation):
    async with new_client() as client:
        for _ in range(5):
            await client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": "x"})
        r = await client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        assert r.status_code == 429
        assert error_code(r) == "ACCOUNT_LOCKED"
        assert r.json()["error"]["params"]["retry_after"] > 0


async def test_login_throttle_is_shared_by_all_api_processes(installation, monkeypatch):
    """The per-IP counter lives in PostgreSQL, so every API process sees it."""
    from app.core.ratelimit import DbRateLimiter
    from app.modules.auth import service as auth_service

    limit = 4
    monkeypatch.setattr(auth_service.login_limiter, "limit", limit)
    async with new_client() as client:
        codes = []
        for i in range(limit + 1):
            body = {"email": f"nobody{i}@example.com", "password": "x"}
            r = await client.post("/api/v1/auth/login", json=body)
            codes.append(r.status_code)
    assert codes == [401] * limit + [429]
    async with owner_sessionmaker()() as db:
        stored = (await db.execute(text("SELECT sum(hits) FROM rate_limit_buckets"))).scalar_one()
    assert stored == limit + 1
    # The limiter of another process (a new instance, nothing in memory) agrees.
    other = DbRateLimiter("login-ip", limit, 60)
    assert await other.hit("127.0.0.1") is False
    assert await other.hit("203.0.113.9") is True  # other addresses are not affected


async def test_csrf_required_for_cookie_sessions(admin: Api):
    body = {"code": "A", "name": "Main"}
    del admin.client.headers["X-CSRF-Token"]
    r = await admin.post(admin.h("/buildings"), body)
    assert r.status_code == 403 and error_code(r) == "CSRF_FAILED"
    admin.client.headers["X-CSRF-Token"] = "forged"
    r = await admin.post(admin.h("/buildings"), body)
    assert r.status_code == 403
    admin.client.headers["X-CSRF-Token"] = admin.me["csrf_token"]
    r = await admin.post(admin.h("/buildings"), body)
    assert r.status_code == 201


async def test_bearer_mode_for_api_clients(installation):
    async with new_client() as client:
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
            headers={"X-Auth-Mode": "bearer"},
        )
        token = r.json()["token"]
        assert token and "set-cookie" not in r.headers
    async with new_client() as client:
        r = await client.post(
            f"/api/v1/hotels/{installation.hotel_id}/buildings",
            json={"code": "B", "name": "B"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 201  # no CSRF needed: bearer tokens are not ambient


async def test_logout_revokes_session(admin: Api):
    assert (await admin.post("/api/v1/auth/logout")).status_code == 204
    r = await admin.get("/api/v1/auth/me")
    assert r.status_code == 401


async def test_admin_revocation_takes_effect_immediately(admin: Api, user_factory):
    clerk = await user_factory("receptionist")
    sessions = (await admin.get(admin.h("/sessions"))).json()
    target = next(s for s in sessions if s["user_email"] == "receptionist-0@example.com")
    assert target["online"] is True
    assert (await admin.delete(admin.h(f"/sessions/{target['id']}"))).status_code == 204
    r = await clerk.get("/api/v1/auth/me")
    assert r.status_code == 401 and error_code(r) == "SESSION_INVALID"


async def test_password_change_revokes_other_sessions(admin: Api, installation):
    async with new_client() as other_client:
        other = Api(other_client, installation.hotel_id)
        await other.login(ADMIN_EMAIL, ADMIN_PASSWORD)
        r = await admin.post(
            "/api/v1/auth/me/password",
            {"current_password": ADMIN_PASSWORD, "new_password": "Another-Secret-9"},
        )
        assert r.status_code == 204
        assert (await other.get("/api/v1/auth/me")).status_code == 401
        assert (await admin.get("/api/v1/auth/me")).status_code == 200


async def test_password_policy(admin: Api):
    r = await admin.post(
        "/api/v1/auth/me/password", {"current_password": ADMIN_PASSWORD, "new_password": "short"}
    )
    assert r.status_code == 422 and error_code(r) == "PASSWORD_TOO_SHORT"
    r = await admin.post(
        "/api/v1/auth/me/password", {"current_password": ADMIN_PASSWORD, "new_password": "password123"}
    )
    assert error_code(r) == "PASSWORD_TOO_COMMON"


async def test_totp_two_factor_flow(admin: Api, installation):
    setup = (await admin.post("/api/v1/auth/me/totp/setup")).json()
    totp = pyotp.TOTP(setup["secret"])
    r = await admin.post("/api/v1/auth/me/totp/enable", {"code": "000000"})
    assert r.status_code == 422 and error_code(r) == "TOTP_INVALID"
    assert (await admin.post("/api/v1/auth/me/totp/enable", {"code": totp.now()})).status_code == 200
    async with new_client() as client:
        api = Api(client)
        r = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD)
        assert r.status_code == 401 and error_code(r) == "TOTP_REQUIRED"
        # The code just used to turn it on is spent; the next one is accepted.
        r = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD, totp_code=totp.at(time.time() + 30))
        assert r.status_code == 200
    # The secret is stored encrypted, never in clear text.
    async with owner_sessionmaker()() as db:
        raw = await db.scalar(text("SELECT totp_secret FROM users"))
    assert setup["secret"].encode() not in raw


async def test_admin_resets_a_lost_authenticator(admin: Api, user_factory):
    clerk = await user_factory("receptionist", "clerk@example.com")
    secret = (await clerk.post("/api/v1/auth/me/totp/setup")).json()["secret"]
    enabled = await clerk.post("/api/v1/auth/me/totp/enable", {"code": pyotp.TOTP(secret).now()})
    assert enabled.status_code == 200
    target = next(u for u in (await admin.get(admin.h("/users"))).json() if u["email"] == "clerk@example.com")
    assert target["totp_enabled"] is True

    # Not one's own (that is done in My account, with the password).
    r = await admin.post(admin.h(f"/users/{admin.me['user']['id']}/totp/reset"))
    assert r.status_code == 403 and error_code(r) == "USE_MY_ACCOUNT"
    # A receptionist cannot do it.
    other = await user_factory("receptionist")
    assert (await other.post(other.h(f"/users/{target['id']}/totp/reset"))).status_code == 403

    r = await admin.post(admin.h(f"/users/{target['id']}/totp/reset"))
    assert r.status_code == 200 and r.json()["totp_enabled"] is False
    # Their sessions ended (the lost device may be in someone's hands)...
    assert (await clerk.get("/api/v1/auth/me")).status_code == 401
    # ...and they sign in with the password alone, then may enrol a new device.
    async with new_client() as client:
        assert (await Api(client).login("clerk@example.com", "Str0ng-Passw0rd")).status_code == 200
    again = await admin.post(admin.h(f"/users/{target['id']}/totp/reset"))
    assert again.status_code == 409 and error_code(again) == "TOTP_NOT_ENABLED"
    logs = (await admin.get(admin.h("/audit-logs"), params={"entity_type": "user"})).json()["items"]
    assert any(e["action"] == "user.totp_reset" for e in logs)


async def test_language_preference_is_per_user(admin: Api, user_factory):
    clerk = await user_factory("receptionist")
    r = await clerk.patch("/api/v1/auth/me", {"preferred_language": "km"})
    assert r.json()["user"]["preferred_language"] == "km"
    r = await admin.patch("/api/v1/auth/me", {"preferred_language": "zh-CN"})
    assert r.json()["user"]["preferred_language"] == "zh-CN"
    assert (await clerk.get("/api/v1/auth/me")).json()["user"]["preferred_language"] == "km"
    r = await admin.patch("/api/v1/auth/me", {"preferred_language": "de"})
    assert r.status_code == 422


async def test_staff_accounts_may_use_internal_domains(admin: Api):
    # Hotels on a private network often use non-public domains for staff.
    r = await admin.post(
        admin.h("/users"),
        {"email": "reception@hotel.lan", "full_name": "Desk", "password": "Str0ng-Passw0rd"},
    )
    assert r.status_code == 201, r.text
    async with new_client() as client:
        r = await Api(client).login("reception@hotel.lan", "Str0ng-Passw0rd")
        assert r.status_code == 200
    # ".local" (Windows and mDNS networks) is accepted too, normalised.
    r = await admin.post(
        admin.h("/users"),
        {"email": "Night.Audit@Hotel.LOCAL", "full_name": "Night", "password": "Str0ng-Passw0rd"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["email"] == "Night.Audit@hotel.local"
    for bad in ("@hotel.local", "a b@hotel.local", "x@.local"):
        r = await admin.post(
            admin.h("/users"), {"email": bad, "full_name": "X", "password": "Str0ng-Passw0rd"}
        )
        assert r.status_code == 422, bad
    async with new_client() as client:
        # Login never rejects an identifier on syntax; it is simply not found.
        r = await Api(client).login("not-an-email", "whatever")
        assert r.status_code == 401 and error_code(r) == "INVALID_CREDENTIALS"
    r = await admin.post(
        admin.h("/users"), {"email": "no-at-sign", "full_name": "X", "password": "Str0ng-Passw0rd"}
    )
    assert r.status_code == 422


async def test_health_identifies_the_server(installation):
    """The desktop shell recognises an HMS server by this answer."""
    async with new_client() as client:
        body = (await client.get("/api/v1/health")).json()
    assert body["status"] == "ok" and body["service"] == "hms" and body["version"]
