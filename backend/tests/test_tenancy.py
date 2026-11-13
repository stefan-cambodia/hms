"""Database-level tenant isolation (row-level security) and least privilege
(migration 0010). The API's own role is used wherever the protection is
under test; the schema owner only prepares data."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.db import owner_sessionmaker, sessionmaker
from app.core.dbroles import RoleError, provision_login_role, runtime_role_posture
from app.core.security import hash_password
from app.core.tenancy import set_tenant, tenant_scope
from app.modules.auth.models import User, UserHotelRole
from app.modules.hotels.bootstrap import seed_hotel_defaults, sync_system_roles
from app.modules.hotels.models import Hotel, Organization
from tests.conftest import Api, Installation, new_client

# Tables without tenant data (no row-level security, by design).
NO_RLS = {"alembic_version", "rate_limit_buckets"}
APPEND_ONLY_NO_UPDATE = {"audit_logs", "login_events", "day_closures"}
APPEND_ONLY_NO_DELETE = {
    "day_closures",
    "audit_logs",
    "login_events",
    "folio_charges",
    "payments",
    "invoices",
    "restaurant_payments",
    "vehicle_rental_payments",
}
DEFINER_FUNCTIONS = {
    "hms_login_org",
    "hms_session_org",
    "hms_installation_initialized",
    "hms_single_organization",
    "hms_channel_connections",
}
OTHER_PASSWORD = "0ther-Hotel-Pass"


async def other_organisation(email: str = "boss@other.example") -> tuple[uuid.UUID, uuid.UUID]:
    """A second organisation with one hotel and a super administrator,
    created behind the API's back (as the schema owner)."""
    async with owner_sessionmaker()() as db:
        org = Organization(name="Other Group")
        db.add(org)
        await db.flush()
        hotel = Hotel(
            organization_id=org.id,
            code="OTHER",
            name="Other Hotel",
            timezone="Asia/Bangkok",
            currency_code="THB",
            default_language="en",
            version=1,
        )
        db.add(hotel)
        await db.flush()
        roles = await sync_system_roles(db, org.id)
        user = User(
            organization_id=org.id,
            email=email,
            full_name="Other Boss",
            password_hash=hash_password(OTHER_PASSWORD),
            is_superadmin=True,
            preferred_language="en",
            version=1,
        )
        db.add(user)
        await db.flush()
        db.add(UserHotelRole(user_id=user.id, hotel_id=hotel.id, role_id=roles["super_admin"].id))
        await seed_hotel_defaults(db, hotel)
        await db.execute(
            text(
                "INSERT INTO buildings (id, hotel_id, code, name, version) VALUES (:i, :h, 'B', 'Secret', 1)"
            ),
            {"i": uuid.uuid4(), "h": hotel.id},
        )
        await db.commit()
        return org.id, hotel.id


async def test_schema_security_invariants(installation: Installation):
    """Every table holds tenant data behind row-level security (or is
    explicitly exempt), and the application role has only what it needs."""
    async with owner_sessionmaker()() as db:
        tables = dict(
            (
                await db.execute(
                    text(
                        "SELECT c.relname, c.relrowsecurity FROM pg_class c "
                        "WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r'"
                    )
                )
            ).all()
        )
        with_policy = set(
            await db.scalars(text("SELECT DISTINCT tablename FROM pg_policies WHERE schemaname = 'public'"))
        )
        missing = sorted(t for t, rls in tables.items() if t not in NO_RLS and not (rls and t in with_policy))
        assert missing == [], f"tables without row-level security: {missing}"

        rows = (
            await db.execute(
                text(
                    "SELECT table_name, privilege_type FROM information_schema.role_table_grants "
                    "WHERE grantee = 'hms_app' AND table_schema = 'public'"
                )
            )
        ).all()
        granted: dict[str, set[str]] = {}
        for table, privilege in rows:
            granted.setdefault(privilege, set()).add(table)
        assert granted["SELECT"] == set(tables)
        assert not granted.get("TRUNCATE") and not granted.get("REFERENCES") and not granted.get("TRIGGER")
        assert APPEND_ONLY_NO_UPDATE.isdisjoint(granted["UPDATE"])
        assert APPEND_ONLY_NO_DELETE.isdisjoint(granted["DELETE"])
        assert "alembic_version" not in granted["INSERT"] | granted["UPDATE"] | granted["DELETE"]

        role = (
            await db.execute(
                text(
                    "SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb, rolcanlogin "
                    "FROM pg_roles WHERE rolname = 'hms_app'"
                )
            )
        ).one()
        assert not any(role)

        definers = (
            await db.execute(
                text(
                    "SELECT p.proname, p.proconfig, has_function_privilege('public', p.oid, 'EXECUTE') "
                    "FROM pg_proc p WHERE p.pronamespace = 'public'::regnamespace AND p.prosecdef"
                )
            )
        ).all()
        assert {name for name, _, _ in definers} == DEFINER_FUNCTIONS
        for name, config, public_can_run in definers:
            assert any(c.startswith("search_path=") for c in config or []), name
            assert not public_can_run, name


async def test_api_role_posture():
    async with sessionmaker()() as db:
        assert (await runtime_role_posture(db)).problems == ()
    async with owner_sessionmaker()() as db:
        assert "superuser" in (await runtime_role_posture(db)).problems


async def test_db_roles_refuses_privileged_or_owner_roles():
    async with owner_sessionmaker()() as db:
        with pytest.raises(RoleError, match="schema owner"):
            await provision_login_role(db, "postgresql+asyncpg://hms:x@localhost/hms")
        await db.execute(text("DROP ROLE IF EXISTS hms_test_admin"))
        await db.execute(text("CREATE ROLE hms_test_admin LOGIN CREATEROLE"))
        await db.commit()
        try:
            with pytest.raises(RoleError, match="administrative"):
                await provision_login_role(db, "postgresql+asyncpg://hms_test_admin:x@localhost/hms")
        finally:
            await db.rollback()
            await db.execute(text("DROP ROLE hms_test_admin"))
            await db.commit()
        # Re-running for the real API role is idempotent.
        assert (
            await provision_login_role(db, "postgresql+asyncpg://hms_api:hms_api_dev_password@x/hms")
            == "hms_api"
        )


async def test_without_a_tenant_nothing_is_visible(admin: Api):
    await admin.post(admin.h("/buildings"), {"code": "A", "name": "Main"})
    async with owner_sessionmaker()() as db:
        tables = list(
            await db.scalars(
                text(
                    "SELECT relname FROM pg_class WHERE relnamespace = 'public'::regnamespace "
                    "AND relkind = 'r' AND relrowsecurity"
                )
            )
        )
        populated = {t for t in tables if await db.scalar(text(f'SELECT count(*) FROM "{t}"'))}  # noqa: S608
    assert {"hotels", "users", "buildings", "amenities", "audit_logs", "user_sessions"} <= populated
    async with sessionmaker()() as db:
        for table in tables:
            assert await db.scalar(text(f'SELECT count(*) FROM "{table}"')) == 0, table  # noqa: S608


async def test_other_organisation_is_invisible_to_the_api_and_to_sql(admin: Api, installation: Installation):
    other_org, other_hotel = await other_organisation()
    mine = uuid.UUID(installation.hotel_id)

    # Through the API: each organisation only sees itself.
    assert (await admin.get(f"/api/v1/hotels/{other_hotel}")).status_code == 404
    async with new_client() as client:
        other = Api(client)
        assert (await other.login("boss@other.example", OTHER_PASSWORD)).status_code == 200
        assert [h["id"] for h in other.me["hotels"]] == [str(other_hotel)]
        assert (await other.get(f"/api/v1/hotels/{mine}")).status_code == 404
        buildings = (await other.get(other.h("/buildings"))).json()
        assert [b["name"] for b in buildings] == ["Secret"]

    # In SQL, even a query naming the other hotel finds nothing, and writing
    # into it is refused.
    async with sessionmaker()() as db:
        await set_tenant(db, uuid.UUID(installation.organization_id))
        count = text("SELECT count(*) FROM buildings WHERE hotel_id = :h")
        assert await db.scalar(count, {"h": other_hotel}) == 0
        assert await db.scalar(text("SELECT count(*) FROM hotels")) == 1
        assert await db.scalar(text("SELECT count(*) FROM organizations")) == 1
        assert await db.scalar(text("SELECT count(*) FROM users WHERE email = 'boss@other.example'")) == 0
        updated = await db.execute(
            text("UPDATE buildings SET name = 'pwned' WHERE hotel_id = :h"), {"h": other_hotel}
        )
        assert updated.rowcount == 0
        with pytest.raises(DBAPIError, match="row-level security"):
            await db.execute(
                text(
                    "INSERT INTO buildings (id, hotel_id, code, name, version) VALUES (:i, :h, 'X', 'X', 1)"
                ),
                {"i": uuid.uuid4(), "h": other_hotel},
            )
        await db.rollback()

    # Naming another organisation's hotel in the hotel scope grants nothing.
    async with sessionmaker()() as db:
        await set_tenant(db, uuid.UUID(installation.organization_id), (other_hotel,))
        assert await db.scalar(text("SELECT count(*) FROM buildings")) == 0
        assert await db.scalar(text("SELECT count(*) FROM amenities")) == 0

    # Background work declares its tenant the same way.
    with tenant_scope(other_org, (other_hotel,)):
        async with sessionmaker()() as db:
            assert await db.scalar(text("SELECT count(*) FROM buildings")) == 1


async def test_hotel_requests_only_see_their_hotel(admin: Api, installation: Installation):
    second = await admin.post(
        "/api/v1/hotels",
        {"code": "SECOND", "name": "Second Hotel", "timezone": "Asia/Phnom_Penh", "currency_code": "USD"},
    )
    assert second.status_code == 201, second.text
    second_id = uuid.UUID(second.json()["id"])
    await admin.post(admin.h("/buildings"), {"code": "A", "name": "First hotel building"})
    r = await admin.post(
        f"/api/v1/hotels/{second_id}/buildings", {"code": "A", "name": "Second hotel building"}
    )
    assert r.status_code == 201, r.text

    org = uuid.UUID(installation.organization_id)
    async with sessionmaker()() as db:
        await set_tenant(db, org)  # organisation-wide request
        assert await db.scalar(text("SELECT count(*) FROM buildings")) == 2
        await set_tenant(db, org, (uuid.UUID(installation.hotel_id),))  # hotel request
        names = list(await db.scalars(text("SELECT name FROM buildings")))
        assert names == ["First hotel building"]
        assert await db.scalar(text("SELECT count(*) FROM hotels")) == 1


async def test_unknown_address_attempts_stay_private_between_organisations(admin: Api):
    async with new_client() as client:
        await client.post("/api/v1/auth/login", json={"email": "typo@example.com", "password": "nope"})
    shown = (await admin.get(admin.h("/login-events"))).json()["items"]
    assert any(e["email"] == "typo@example.com" for e in shown)
    # With a second organisation in the database, nobody can tell whose
    # address that attempt was aimed at: it is no longer shown.
    await other_organisation()
    shown = (await admin.get(admin.h("/login-events"))).json()["items"]
    assert not any(e["email"] == "typo@example.com" for e in shown)
