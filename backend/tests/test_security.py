"""Access control over every API operation (security audit, phase 10).

The operations are taken from the OpenAPI schema, so an endpoint added later
is covered automatically: it must require a session, refuse cookie requests
without the CSRF token, hide other organisations' hotels, and refuse users
without the right permission — or be added, after review, to one of the
explicit lists below.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator

import httpx

from app.main import app
from tests.conftest import Api, Installation, error_code, new_client
from tests.test_tenancy import other_organisation

METHODS = ("get", "post", "put", "patch", "delete")
API = "/api/v1"

# Reachable without a session.
PUBLIC = {("GET", f"{API}/health"), ("POST", f"{API}/auth/login")}

# Hotel operations open to every member of the hotel, whatever their role
# (reviewed: hotel identity and reference data needed by every screen).
MEMBERSHIP_ONLY: set[tuple[str, str]] = set()


def operations() -> Iterator[tuple[str, str, dict[str, dict]]]:
    for path, item in app.openapi()["paths"].items():
        for method, op in item.items():
            if method in METHODS:
                params = {p["name"]: p["schema"] for p in op.get("parameters", []) if p["in"] == "path"}
                yield method.upper(), path, params


def concrete(path: str, params: dict[str, dict], hotel_id: str) -> str:
    def value(match: re.Match[str]) -> str:
        name = match.group(1)
        if name == "hotel_id":
            return hotel_id
        schema = params.get(name, {})
        if schema.get("enum"):
            return str(schema["enum"][0])
        if schema.get("type") == "integer":
            return "1"
        return str(uuid.uuid4())

    return re.sub(r"\{(\w+)\}", value, path)


async def call(client: httpx.AsyncClient, method: str, url: str) -> httpx.Response:
    return await client.request(method, url, json={} if method != "GET" else None)


def test_the_schema_lists_every_operation():
    ops = list(operations())
    assert len(ops) > 200
    assert (
        "POST",
        f"{API}/hotels/{{hotel_id}}/backups/restore",
        {"hotel_id": {"type": "string", "format": "uuid"}},
    ) in [
        (m, p, {k: {"type": v.get("type"), "format": v.get("format")} for k, v in prm.items()})
        for m, p, prm in ops
    ]


async def test_every_operation_requires_a_session(installation: Installation):
    unexpected = []
    async with new_client() as client:
        for method, path, params in operations():
            if (method, path) in PUBLIC:
                continue
            r = await call(client, method, concrete(path, params, installation.hotel_id))
            if r.status_code != 401:
                unexpected.append((method, path, r.status_code))
    assert unexpected == []


async def test_cookie_sessions_need_the_csrf_token(admin: Api):
    unexpected = []
    async with new_client() as client:
        client.cookies.update(admin.client.cookies)  # same session, no X-CSRF-Token header
        for method, path, params in operations():
            if method == "GET" or (method, path) in PUBLIC:
                continue
            r = await call(client, method, concrete(path, params, admin.hotel_id or ""))
            if r.status_code != 403 or error_code(r) != "CSRF_FAILED":
                unexpected.append((method, path, r.status_code))
    assert unexpected == []
    assert (await admin.get("/api/v1/auth/me")).status_code == 200  # nothing was changed


async def test_other_organisations_hotels_do_not_exist(admin: Api):
    _, other_hotel = await other_organisation()
    unexpected = []
    for method, path, params in operations():
        if "{hotel_id}" not in path:
            continue
        r = await call(admin.client, method, concrete(path, params, str(other_hotel)))
        if r.status_code != 404 or error_code(r) != "HOTEL_NOT_FOUND":
            unexpected.append((method, path, r.status_code))
    assert unexpected == []


async def test_without_permissions_hotel_operations_are_refused(admin: Api):
    role = await admin.post(
        admin.h("/roles"), {"code": "nothing", "name": "No permission", "permissions": []}
    )
    assert role.status_code == 201, role.text
    r = await admin.post(
        admin.h("/users"),
        {
            "email": "nobody@example.com",
            "full_name": "Nobody",
            "password": "Str0ng-Passw0rd",
            "role_ids": [role.json()["id"]],
        },
    )
    assert r.status_code == 201, r.text
    async with new_client() as client:
        nobody = Api(client, admin.hotel_id)
        assert (await nobody.login("nobody@example.com", "Str0ng-Passw0rd")).status_code == 200
        allowed, errors = set(), []
        for method, path, params in operations():
            if "{hotel_id}" not in path:
                continue
            r = await call(client, method, concrete(path, params, admin.hotel_id or ""))
            if r.status_code >= 500:
                errors.append((method, path, r.status_code))
            elif r.status_code != 403:
                allowed.add((method, path))
    assert errors == []
    assert allowed == MEMBERSHIP_ONLY
