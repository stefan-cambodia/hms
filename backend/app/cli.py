"""Administrative command line.

    python -m app.cli bootstrap --org "My Hotels" --hotel "Seaside Hotel" --code SEASIDE \
        --admin-email admin@example.com --admin-name "Admin" [--timezone Asia/Phnom_Penh] \
        [--currency USD] [--language en]
    (the admin password is read from HMS_ADMIN_PASSWORD or prompted)

    python -m app.cli sync-roles      re-apply system role permissions after an upgrade
    python -m app.cli db-roles        create/update the API's database login role
                                      (name and password taken from HMS_DATABASE_URL)

sync-roles and db-roles are installation-wide: they connect as the schema
owner (HMS_MIGRATION_DATABASE_URL). The other commands use the application
role like the API.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys

from sqlalchemy import select

import app.models  # noqa: F401
from app.core.config import get_settings
from app.core.db import dispose_engine, owner_sessionmaker, sessionmaker
from app.core.dbroles import RoleError, provision_login_role
from app.core.errors import AppError
from app.modules.hotels.bootstrap import bootstrap, sync_system_roles
from app.modules.hotels.models import Organization


async def _bootstrap(args: argparse.Namespace) -> int:
    password = os.environ.get("HMS_ADMIN_PASSWORD") or getpass.getpass("Admin password: ")
    async with sessionmaker()() as db:
        try:
            result = await bootstrap(
                db,
                organization_name=args.org,
                hotel_name=args.hotel,
                hotel_code=args.code,
                admin_email=args.admin_email,
                admin_password=password,
                admin_name=args.admin_name,
                timezone=args.timezone,
                currency_code=args.currency,
                default_language=args.language,
            )
        except AppError as exc:
            print(f"error: {exc.code}", file=sys.stderr)
            return 1
    print(
        f"Created organisation {result.organization.id}, hotel {result.hotel.id}, admin {result.admin.email}"
    )
    return 0


async def _seed_demo(args: argparse.Namespace) -> int:
    from app.demo import SeedError, seed_demo

    password = os.environ.get("HMS_ADMIN_PASSWORD") or getpass.getpass("Admin password: ")
    try:
        print(await seed_demo(args.admin_email, password))
    except SeedError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


async def _db_roles(_: argparse.Namespace) -> int:
    async with owner_sessionmaker()() as db:
        try:
            name = await provision_login_role(db, get_settings().database_url)
        except RoleError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    print(f"Database role {name} is ready (member of hms_app)")
    return 0


async def _sync_roles(_: argparse.Namespace) -> int:
    async with owner_sessionmaker()() as db:
        for org_id in await db.scalars(select(Organization.id)):
            await sync_system_roles(db, org_id)
        await db.commit()
    print("System roles synchronised")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="hms")
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bootstrap", help="initialise an empty installation")
    b.add_argument("--org", required=True)
    b.add_argument("--hotel", required=True)
    b.add_argument("--code", required=True)
    b.add_argument("--admin-email", required=True)
    b.add_argument("--admin-name", required=True)
    b.add_argument("--timezone", default="UTC")
    b.add_argument("--currency", default="USD")
    b.add_argument("--language", default="en", choices=["en", "fr", "zh-CN", "ru", "km"])
    sub.add_parser("sync-roles", help="re-apply system role permission sets")
    sub.add_parser("db-roles", help="create or update the API's database login role")
    d = sub.add_parser("seed-demo", help="fill an empty hotel with the demo content (training, tests)")
    d.add_argument("--admin-email", required=True)
    args = parser.parse_args()
    handler = {
        "bootstrap": _bootstrap,
        "sync-roles": _sync_roles,
        "db-roles": _db_roles,
        "seed-demo": _seed_demo,
    }[args.cmd]

    async def run() -> int:
        try:
            return await handler(args)
        finally:
            await dispose_engine()

    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
