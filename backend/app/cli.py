"""Administrative command line.

    python -m app.cli bootstrap --org "My Hotels" --hotel "Seaside Hotel" --code SEASIDE \
        --admin-email admin@example.com --admin-name "Admin" [--timezone Asia/Phnom_Penh] \
        [--currency USD] [--language en]
    (the admin password is read from HMS_ADMIN_PASSWORD or prompted)

    python -m app.cli sync-roles      re-apply system role permissions after an upgrade
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys

from sqlalchemy import select

import app.models  # noqa: F401
from app.core.db import dispose_engine, sessionmaker
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


async def _sync_roles(_: argparse.Namespace) -> int:
    async with sessionmaker()() as db:
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
    d = sub.add_parser("seed-demo", help="fill an empty hotel with the demo content (training, tests)")
    d.add_argument("--admin-email", required=True)
    args = parser.parse_args()
    handler = {"bootstrap": _bootstrap, "sync-roles": _sync_roles, "seed-demo": _seed_demo}[args.cmd]

    async def run() -> int:
        try:
            return await handler(args)
        finally:
            await dispose_engine()

    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
