"""Database roles (least privilege, migration 0010).

* The schema owner (HMS_MIGRATION_DATABASE_URL) runs migrations and
  installation-wide commands. The API never uses it.
* `hms_app` (NOLOGIN) holds the application's privileges: rows only, no
  schema changes, no TRUNCATE, no UPDATE/DELETE of append-only records, and
  row-level security applies to it.
* The API logs in with the role named in HMS_DATABASE_URL, a member of
  `hms_app`, created or updated by `hms db-roles`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("hms.db")
APP_GROUP = "hms_app"
_PROVISION = text(
    """
    DO $$
    DECLARE n text := current_setting('hms.role_name');
            p text := current_setting('hms.role_password');
            attrs text := 'LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS INHERIT';
    BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = n) THEN
        EXECUTE format('ALTER ROLE %I WITH ' || attrs || ' PASSWORD %L', n, p);
      ELSE
        EXECUTE format('CREATE ROLE %I WITH ' || attrs || ' PASSWORD %L', n, p);
      END IF;
      EXECUTE format('GRANT hms_app TO %I', n);
    END $$;
    """
)


class RoleError(Exception):
    pass


async def provision_login_role(owner: AsyncSession, app_url: str) -> str:
    """Create or update the API's login role from HMS_DATABASE_URL (name and
    password) and make it a member of hms_app. Refuses to touch a role that
    is the owner, a superuser, or owns tables: that would be a configuration
    mistake, and altering such a role could lock an administrator out."""
    url = make_url(app_url)
    name, password = url.username, url.password
    if not name or not password:
        raise RoleError("HMS_DATABASE_URL must contain a user name and a password")
    current = await owner.scalar(text("SELECT current_user"))
    if name == current:
        raise RoleError(
            f"HMS_DATABASE_URL uses the schema owner ({name}); the API needs its own role "
            "(for example hms_api) so that row-level security applies"
        )
    if await owner.scalar(
        text("SELECT NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :g)"), {"g": APP_GROUP}
    ):
        raise RoleError("role hms_app is missing: run the migrations first (alembic upgrade head)")
    row = (
        await owner.execute(
            text("SELECT rolsuper OR rolbypassrls OR rolcreaterole FROM pg_roles WHERE rolname = :n"),
            {"n": name},
        )
    ).one_or_none()
    if row is not None and row[0]:
        raise RoleError(f"role {name} has administrative attributes; choose a dedicated role name")
    owned = await owner.scalar(
        text(
            "SELECT count(*) FROM pg_class c JOIN pg_roles r ON r.oid = c.relowner "
            "WHERE r.rolname = :n AND c.relnamespace = 'public'::regnamespace"
        ),
        {"n": name},
    )
    if owned:
        raise RoleError(f"role {name} owns {owned} objects; choose a dedicated role name")
    # The password travels as a bound parameter, never inside the SQL text.
    await owner.execute(
        text("SELECT set_config('hms.role_name', :n, true), set_config('hms.role_password', :p, true)"),
        {"n": name, "p": password},
    )
    await owner.execute(_PROVISION)
    await owner.commit()
    return name


@dataclass(frozen=True)
class RolePosture:
    role: str
    problems: tuple[str, ...]


async def runtime_role_posture(db: AsyncSession) -> RolePosture:
    """Does the API's own connection keep the database protections in force?"""
    row = (
        await db.execute(
            text(
                """
                SELECT r.rolname, r.rolsuper, r.rolbypassrls,
                  (SELECT count(*) FROM pg_class c
                    WHERE c.relowner = r.oid AND c.relnamespace = 'public'::regnamespace) AS owned,
                  EXISTS (SELECT 1 FROM pg_auth_members m JOIN pg_roles g ON g.oid = m.roleid
                          WHERE g.rolname = :g AND m.member = r.oid) AS member
                FROM pg_roles r WHERE r.rolname = current_user
                """
            ),
            {"g": APP_GROUP},
        )
    ).one()
    await db.rollback()
    problems: list[str] = []
    if row.rolsuper:
        problems.append("superuser")
    if row.rolbypassrls:
        problems.append("bypasses row-level security")
    if row.owned:
        problems.append("owns the schema's tables")
    if not row.member:
        problems.append(f"not a member of {APP_GROUP}")
    return RolePosture(role=row.rolname, problems=tuple(problems))
