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
from app.modules.channels.models import (
    ChannelConnection,
    ChannelDirtyRange,
    ChannelMessage,
    ChannelSyncStatus,
)
from app.modules.channels.sync import is_due, sync_connection
from app.modules.hotels.models import Hotel

logger = logging.getLogger("hms.channels")
LOCK_KEY = 0x484D53_4348  # "HMSCH"
MESSAGE_RETENTION = timedelta(days=30)


async def due_connections(now: datetime) -> list[ChannelConnection]:
    async with sessionmaker()() as db:
        rows = (
            await db.execute(
                select(ChannelConnection, ChannelSyncStatus, Hotel)
                .join(ChannelSyncStatus, ChannelSyncStatus.connection_id == ChannelConnection.id)
                .join(Hotel, Hotel.id == ChannelConnection.hotel_id)
                .where(ChannelConnection.enabled.is_(True))
            )
        ).all()
        dirty = set(await db.scalars(select(ChannelDirtyRange.connection_id).distinct()))
    return [c for c, s, h in rows if is_due(c, s, h.today(), c.id in dirty, now)]


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
    async with sessionmaker()() as db:
        await db.execute(
            delete(ChannelMessage).where(ChannelMessage.at < datetime.now(UTC) - MESSAGE_RETENTION)
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
