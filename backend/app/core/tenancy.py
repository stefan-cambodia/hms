"""Tenant context for PostgreSQL row-level security (migration 0010).

Every transaction declares which organisation, and optionally which hotels,
it works for. The database then only shows and accepts rows of that tenant,
whatever the SQL says: a query that forgets its `hotel_id` filter returns the
current hotel's rows, never another organisation's.

Two ways to declare it:

* request code calls `await set_tenant(db, org_id, hotel_ids)` on its session
  (done by the auth dependencies: organisation after the session is resolved,
  hotel after the hotel permission check);
* background code (channel worker, CLI) wraps its work in
  `with tenant_scope(org_id, hotel_ids):` — every session opened inside, in
  this task, uses that tenant.

The values are applied with `set_config(..., is_local => true)` at the start
of each transaction, so they can never leak to another request through the
connection pool.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Iterable, Iterator
from contextvars import ContextVar
from dataclasses import dataclass

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

_INFO_KEY = "hms_tenant"
_APPLY = text("SELECT set_config('hms.org_id', :org, true), set_config('hms.hotel_ids', :hotels, true)")


@dataclass(frozen=True, slots=True)
class Tenant:
    organization_id: uuid.UUID
    # None: every hotel of the organisation. Otherwise only these hotels.
    hotel_ids: tuple[uuid.UUID, ...] | None = None

    def params(self) -> dict[str, str]:
        hotels = "" if self.hotel_ids is None else ",".join(str(h) for h in self.hotel_ids)
        if self.hotel_ids is not None and not self.hotel_ids:
            # An empty hotel list must mean "no hotel", not "all hotels".
            hotels = str(uuid.UUID(int=0))
        return {"org": str(self.organization_id), "hotels": hotels}


_scope: ContextVar[Tenant | None] = ContextVar("hms_tenant_scope", default=None)


class TenantSession(Session):
    """Session class used by the application's sessionmaker."""


@event.listens_for(TenantSession, "after_begin")
def _apply_tenant(session: Session, transaction, connection) -> None:  # type: ignore[no-untyped-def]
    tenant = session.info.get(_INFO_KEY) or _scope.get()
    if tenant is not None:
        connection.execute(_APPLY, tenant.params())


def _tenant(organization_id: uuid.UUID, hotel_ids: Iterable[uuid.UUID] | None) -> Tenant:
    return Tenant(organization_id, None if hotel_ids is None else tuple(hotel_ids))


async def set_tenant(
    db: AsyncSession, organization_id: uuid.UUID, hotel_ids: Iterable[uuid.UUID] | None = None
) -> None:
    """Declare the tenant of this session, now and for its later transactions."""
    tenant = _tenant(organization_id, hotel_ids)
    db.info[_INFO_KEY] = tenant
    if db.in_transaction():
        await db.execute(_APPLY, tenant.params())


def current_tenant(db: AsyncSession) -> Tenant | None:
    return db.info.get(_INFO_KEY) or _scope.get()


@contextlib.contextmanager
def tenant_scope(
    organization_id: uuid.UUID, hotel_ids: Iterable[uuid.UUID] | None = None
) -> Iterator[Tenant]:
    """Background work for one tenant: sessions opened inside use it."""
    tenant = _tenant(organization_id, hotel_ids)
    token = _scope.set(tenant)
    try:
        yield tenant
    finally:
        _scope.reset(token)
