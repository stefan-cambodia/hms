"""WebSocket fan-out of committed database events.

Each API process keeps one dedicated PostgreSQL connection LISTENing on
`hms_events` and forwards every notification to the sockets subscribed to that
hotel, filtered by the permission needed to see that kind of entity. If the
LISTEN connection drops, every client is told to `resync` (refetch everything)
once it is re-established, because notifications may have been missed.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

import asyncpg
from fastapi import WebSocket

from app.core.config import get_settings
from app.core.events import CHANNEL
from app.core.permissions import P

log = logging.getLogger("hms.realtime")

# Permission a client needs to receive events about an entity type.
ENTITY_PERMISSIONS: dict[str, str] = {
    "reservation": P.RESERVATIONS_VIEW,
    "guest": P.GUESTS_VIEW,
    "payment": P.PAYMENTS_VIEW,
    "invoice": P.INVOICES_VIEW,
    "housekeeping_task": P.HOUSEKEEPING_VIEW,
    "maintenance_request": P.MAINTENANCE_VIEW,
    "rate": P.PRICING_VIEW,
    "rate_plan": P.PRICING_VIEW,
    "channel": P.CHANNELS_VIEW,
    "user": P.USERS_VIEW,
    "role": P.USERS_VIEW,
    "session": P.USERS_VIEW,
}
DEFAULT_PERMISSION = P.HOTEL_VIEW


@dataclass(eq=False)
class Client:
    websocket: WebSocket
    user_id: uuid.UUID
    session_id: uuid.UUID
    hotel_id: uuid.UUID | None = None
    permissions: frozenset[str] = frozenset()
    queue: asyncio.Queue[dict[str, Any]] = field(default_factory=lambda: asyncio.Queue(maxsize=500))

    def offer(self, message: dict[str, Any]) -> None:
        try:
            self.queue.put_nowait(message)
        except asyncio.QueueFull:
            # A client too slow to drain 500 events gets a resync instead.
            with contextlib.suppress(asyncio.QueueEmpty):
                while True:
                    self.queue.get_nowait()
            self.queue.put_nowait({"type": "resync"})


class Hub:
    def __init__(self) -> None:
        self._clients: set[Client] = set()
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()
        self.listening = asyncio.Event()

    @property
    def clients(self) -> set[Client]:
        return self._clients

    def register(self, client: Client) -> None:
        self._clients.add(client)

    def unregister(self, client: Client) -> None:
        self._clients.discard(client)

    def dispatch(self, payload: dict[str, Any]) -> None:
        hotel_id = payload.get("hotel_id")
        needed = ENTITY_PERMISSIONS.get(payload.get("entity", ""), DEFAULT_PERMISSION)
        message = {"type": "event", **payload}
        for c in list(self._clients):
            if c.hotel_id is None:
                continue
            if hotel_id is not None and str(c.hotel_id) != hotel_id:
                continue
            if needed not in c.permissions:
                continue
            c.offer(message)

    def broadcast_resync(self) -> None:
        for c in list(self._clients):
            c.offer({"type": "resync"})

    def revoke_session(self, session_id: uuid.UUID) -> None:
        for c in list(self._clients):
            if c.session_id == session_id:
                c.offer({"type": "session_revoked"})

    # --- LISTEN loop -----------------------------------------------------------

    def _on_notify(self, _conn: Any, _pid: int, _channel: str, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except ValueError:
            log.warning("Ignoring malformed event payload")
            return
        self.dispatch(payload)

    async def _listen_forever(self) -> None:
        dsn = get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        backoff = 1.0
        first = True
        while not self._stopping.is_set():
            conn: asyncpg.Connection | None = None
            try:
                conn = await asyncpg.connect(dsn)
                await conn.add_listener(CHANNEL, self._on_notify)
                self.listening.set()
                if not first:
                    self.broadcast_resync()
                first = False
                backoff = 1.0
                log.info("Realtime listener connected")
                while not self._stopping.is_set() and not conn.is_closed():
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(self._stopping.wait(), timeout=15)
                    if not self._stopping.is_set():
                        await conn.execute("SELECT 1")  # detect dead connections
            except (OSError, asyncpg.PostgresError, asyncpg.InterfaceError) as exc:
                log.warning("Realtime listener error: %s", exc)
            finally:
                self.listening.clear()
                if conn is not None and not conn.is_closed():
                    with contextlib.suppress(Exception):
                        await conn.close()
            if not self._stopping.is_set():
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    async def start(self) -> None:
        self._stopping.clear()
        self._task = asyncio.create_task(self._listen_forever(), name="realtime-listener")

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None


hub = Hub()
