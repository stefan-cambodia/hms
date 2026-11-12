"""Test fixtures. Tests run against a real PostgreSQL database (`hms_test`)
because integrity rules live in the database (constraints, triggers)."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any

_TEST_DB = "hms_test"
os.environ["HMS_DATABASE_URL"] = os.environ.get(
    "HMS_TEST_DATABASE_URL",
    f"postgresql+asyncpg://hms:hms_dev_password@127.0.0.1:54329/{_TEST_DB}",
)
os.environ["HMS_ENV"] = "test"
os.environ["HMS_COOKIE_SECURE"] = "false"
os.environ["HMS_LOGIN_RATE_PER_MINUTE"] = "10000"

import asyncpg  # noqa: E402
import httpx  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402

import app.models  # noqa: E402,F401
from app.core.config import get_settings  # noqa: E402
from app.core.db import dispose_engine, sessionmaker  # noqa: E402
from app.core.models import Base  # noqa: E402
from app.main import app  # noqa: E402
from app.modules.auth.service import login_limiter  # noqa: E402
from app.modules.hotels.bootstrap import bootstrap  # noqa: E402

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "Correct-Horse-42"
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _dsn(database: str) -> str:
    url = get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return url.rsplit("/", 1)[0] + "/" + database


@pytest.fixture(scope="session", autouse=True)
async def database():
    test_db = get_settings().database_url.rsplit("/", 1)[1]
    conn = await asyncpg.connect(_dsn("postgres"))
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{test_db}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{test_db}"')
    finally:
        await conn.close()
    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "migrations"))
    await asyncio.to_thread(command.upgrade, cfg, "head")
    yield
    await dispose_engine()


@pytest.fixture(autouse=True)
async def clean_tables(database):
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    async with sessionmaker()() as db:
        await db.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        await db.commit()
    login_limiter.reset()
    yield


class Api:
    """httpx client bound to a hotel, with CSRF handling for cookie sessions."""

    def __init__(self, client: httpx.AsyncClient, hotel_id: str | None = None) -> None:
        self.client = client
        self.hotel_id = hotel_id
        self.me: dict[str, Any] = {}

    def h(self, path: str) -> str:
        return f"/api/v1/hotels/{self.hotel_id}{path}"

    async def login(self, email: str, password: str, **extra: Any) -> httpx.Response:
        r = await self.client.post("/api/v1/auth/login", json={"email": email, "password": password, **extra})
        if r.status_code == 200:
            self.me = r.json()
            self.client.headers["X-CSRF-Token"] = self.me["csrf_token"]
            if self.hotel_id is None and self.me["hotels"]:
                self.hotel_id = self.me["hotels"][0]["id"]
        return r

    async def get(self, url: str, **kw: Any) -> httpx.Response:
        return await self.client.get(url, **kw)

    async def post(self, url: str, json: Any = None, **kw: Any) -> httpx.Response:
        return await self.client.post(url, json=json, **kw)

    async def patch(self, url: str, json: Any = None, **kw: Any) -> httpx.Response:
        return await self.client.patch(url, json=json, **kw)

    async def put(self, url: str, json: Any = None, **kw: Any) -> httpx.Response:
        return await self.client.put(url, json=json, **kw)

    async def delete(self, url: str, **kw: Any) -> httpx.Response:
        return await self.client.delete(url, **kw)


def new_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


@dataclass
class Installation:
    organization_id: str
    hotel_id: str
    admin_id: str


@pytest.fixture
async def installation() -> Installation:
    async with sessionmaker()() as db:
        result = await bootstrap(
            db,
            organization_name="Test Group",
            hotel_name="Test Hotel",
            hotel_code="TEST",
            admin_email=ADMIN_EMAIL,
            admin_password=ADMIN_PASSWORD,
            admin_name="Admin",
            timezone="Asia/Phnom_Penh",
            currency_code="USD",
        )
        return Installation(str(result.organization.id), str(result.hotel.id), str(result.admin.id))


@pytest.fixture
async def admin(installation: Installation):
    async with new_client() as client:
        api = Api(client, installation.hotel_id)
        r = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD)
        assert r.status_code == 200, r.text
        yield api


async def role_id(api: Api, code: str) -> str:
    roles = (await api.get(api.h("/roles"))).json()
    return next(r["id"] for r in roles if r["code"] == code)


async def make_user(admin: Api, email: str, role_code: str, password: str = "Str0ng-Passw0rd") -> dict:
    r = await admin.post(
        admin.h("/users"),
        {
            "email": email,
            "full_name": email.split("@")[0],
            "password": password,
            "role_ids": [await role_id(admin, role_code)],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
async def user_factory(admin: Api):
    """Create a user with a role in the admin's hotel and return a logged-in Api."""
    clients: list[httpx.AsyncClient] = []

    async def factory(role_code: str, email: str | None = None) -> Api:
        email = email or f"{role_code}-{len(clients)}@example.com"
        await make_user(admin, email, role_code)
        client = new_client()
        clients.append(client)
        api = Api(client, admin.hotel_id)
        r = await api.login(email, "Str0ng-Passw0rd")
        assert r.status_code == 200, r.text
        return api

    yield factory
    for c in clients:
        await c.aclose()


def error_code(response: httpx.Response) -> str:
    return response.json()["error"]["code"]
