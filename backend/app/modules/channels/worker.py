"""Background loop that keeps channels in sync.

Exactly one API process runs it at a time: the loop holds a PostgreSQL
session-level advisory lock on a dedicated connection; the other processes
wait and take over if the leader stops. Every few seconds it looks for
connections with work due (pending changes, the daily horizon extension, a
reservation pull) and synchronises them one after the other, so there is
never more than one request in flight per property.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, text

from app.core.db import get_engine, sessionmaker
from app.core.tenancy import tenant_scope
from app.modules.channels.models import (
    ChannelConnection,
    ChannelDirtyRange,
    ChannelMessage,
    ChannelSyncStatus,
)
from app.modules.channels.sync import connection_refs, is_due, sync_connection
from app.modules.hotels.models import Hotel

logger = logging.getLogger("hms.channels")
LOCK_KEY = 0x484D53_4348  # "HMSCH"
MESSAGE_RETENTION = timedelta(days=30)


async def due_connections(now: datetime) -> list[ChannelConnection]:
    due: list[ChannelConnection] = []
    for ref in await connection_refs():
        if not ref.enabled:
            continue
        with tenant_scope(ref.organization_id, (ref.hotel_id,)):
            async with sessionmaker()() as db:
                row = (
                    await db.execute(
                        select(ChannelConnection, ChannelSyncStatus, Hotel)
                        .join(ChannelSyncStatus, ChannelSyncStatus.connection_id == ChannelConnection.id)
                        .join(Hotel, Hotel.id == ChannelConnection.hotel_id)
                        .where(ChannelConnection.id == ref.id)
                    )
                ).one_or_none()
                if row is None:
                    continue
                conn, status, hotel = row
                dirty = await db.scalar(
                    select(ChannelDirtyRange.id).where(ChannelDirtyRange.connection_id == conn.id).limit(1)
                )
            if is_due(conn, status, hotel.today(), dirty is not None, now):
                due.append(conn)
    return due


async def run_once(now: datetime | None = None) -> int:
    """Synchronise every connection with work due. Returns how many ran."""
    now = now or datetime.now(UTC)
    count = 0
    for conn in await due_connections(now):
        try:
            await sync_connection(conn.id, now=now)
        except Exception:
            logger.exception("channel sync failed for connection %s", conn.id)
        count += 1
    return count


async def purge_old_messages() -> None:
    cutoff = datetime.now(UTC) - MESSAGE_RETENTION
    for ref in await connection_refs():
        with tenant_scope(ref.organization_id, (ref.hotel_id,)):
            async with sessionmaker()() as db:
                await db.execute(
                    delete(ChannelMessage).where(
                        ChannelMessage.connection_id == ref.id, ChannelMessage.at < cutoff
                    )
                )
                await db.commit()


class ChannelWorker:
    def __init__(self, interval: float = 5.0) -> None:
        self.interval = interval
        self._task: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="channel-worker")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def wake(self) -> None:
        self._wake.set()

    async def _run(self) -> None:
        while True:
            try:
                async with get_engine().connect() as raw:
                    lock = await raw.execution_options(isolation_level="AUTOCOMMIT")
                    leader = (
                        await lock.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY})
                    ).scalar()
                    if not leader:
                        await asyncio.sleep(30)
                        continue
                    logger.info("channel worker: this process is the leader")
                    last_purge = datetime.min.replace(tzinfo=UTC)
                    while True:
                        await run_once()
                        if datetime.now(UTC) - last_purge > timedelta(hours=1):
                            await purge_old_messages()
                            last_purge = datetime.now(UTC)
                        self._wake.clear()
                        try:
                            await asyncio.wait_for(self._wake.wait(), timeout=self.interval)
                        except TimeoutError:
                            pass
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("channel worker loop error; restarting in 30 s")
                await asyncio.sleep(30)


worker = ChannelWorker()
