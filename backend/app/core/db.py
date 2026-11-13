from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings
from app.core.tenancy import TenantSession

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None
_owner_engine: AsyncEngine | None = None


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            pool_size=settings.db_pool_size,
            pool_pre_ping=True,
        )
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False, sync_session_class=TenantSession)
    return _engine


def sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Sessions of the application role: row-level security applies, so a
    tenant must be declared (app/core/tenancy.py) before reading tenant data."""
    get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


def owner_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Sessions of the schema owner (HMS_MIGRATION_DATABASE_URL). Only for
    installation-wide administration commands; never used by the API."""
    global _owner_engine
    if _owner_engine is None:
        _owner_engine = create_async_engine(get_settings().migration_database_url, pool_size=2)
    return async_sessionmaker(_owner_engine, expire_on_commit=False)


async def dispose_engine() -> None:
    global _engine, _sessionmaker, _owner_engine
    for engine in (_engine, _owner_engine):
        if engine is not None:
            await engine.dispose()
    _engine = None
    _sessionmaker = None
    _owner_engine = None


async def get_db() -> AsyncIterator[AsyncSession]:
    """Request-scoped session. Services own transaction boundaries and commit
    explicitly; anything left uncommitted is rolled back here."""
    async with sessionmaker()() as session:
        try:
            yield session
        finally:
            if session.in_transaction():
                await session.rollback()
