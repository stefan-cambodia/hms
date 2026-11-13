"""WebSocket endpoint.

Protocol (JSON text frames):
  client -> {"type": "auth", "token": "..."}           (only if no session cookie)
  client -> {"type": "subscribe", "hotel_id": "..."}
  server -> {"type": "ready", "hotel_id": "..."}
  server -> {"type": "event", "entity": "...", "action": "...", "id": "...", ...}
  server -> {"type": "resync"}       refetch everything (events may have been missed)
  server -> {"type": "ping"}         client answers {"type": "pong"}
Close codes: 4401 unauthenticated / session revoked, 4403 forbidden origin or hotel.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from urllib.parse import urlparse

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import get_settings
from app.core.db import sessionmaker
from app.core.tenancy import tenant_scope
from app.modules.auth import service as auth_service
from app.modules.auth import twofactor
from app.modules.auth.deps import SESSION_COOKIE
from app.modules.realtime.hub import Client, hub

router = APIRouter()

PING_INTERVAL = 25
SESSION_CHECK_INTERVAL = 60
AUTH_TIMEOUT = 10


def _origin_allowed(ws: WebSocket) -> bool:
    origin = ws.headers.get("origin")
    if origin is None:
        return True  # non-browser client (no ambient credentials to hijack)
    allowed = get_settings().allowed_origins
    if allowed:
        return origin in allowed
    host = ws.headers.get("host", "")
    return urlparse(origin).netloc == host


async def _receive_json(ws: WebSocket, timeout: float) -> dict:
    raw = await asyncio.wait_for(ws.receive_text(), timeout=timeout)
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("expected object")
    return data


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    if not _origin_allowed(ws):
        await ws.close(code=4403)
        return
    await ws.accept()
    token = ws.cookies.get(SESSION_COOKIE)
    try:
        if not token:
            msg = await _receive_json(ws, AUTH_TIMEOUT)
            if msg.get("type") != "auth" or not isinstance(msg.get("token"), str):
                await ws.close(code=4401)
                return
            token = msg["token"]
        async with sessionmaker()() as db:
            resolved = await auth_service.resolve_session(db, token)
            if resolved is None:
                await ws.close(code=4401)
                return
            session, user = resolved
            if not user.totp_enabled and await twofactor.required_for(db, user):
                await ws.close(code=4403)  # two-factor must be set up first
                return
            perms = await auth_service.hotel_permissions(db, user)
    except (TimeoutError, ValueError, WebSocketDisconnect):
        with contextlib.suppress(Exception):
            await ws.close(code=4401)
        return

    client = Client(websocket=ws, user_id=user.id, session_id=session.id)
    hub.register(client)
    sender = asyncio.create_task(_sender(client))
    checker = asyncio.create_task(_session_checker(client, user.organization_id))
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            if not isinstance(msg, dict):
                continue
            kind = msg.get("type")
            if kind == "subscribe":
                try:
                    hotel_id = uuid.UUID(str(msg.get("hotel_id")))
                except ValueError:
                    await ws.close(code=4403)
                    break
                if hotel_id not in perms:
                    await ws.close(code=4403)
                    break
                client.hotel_id = hotel_id
                client.permissions = perms[hotel_id]
                client.offer({"type": "ready", "hotel_id": str(hotel_id)})
            # "pong" and unknown messages are ignored.
    except (WebSocketDisconnect, ValueError, RuntimeError):
        pass
    finally:
        hub.unregister(client)
        sender.cancel()
        checker.cancel()
        for t in (sender, checker):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t


async def _sender(client: Client) -> None:
    ws = client.websocket
    while True:
        try:
            msg = await asyncio.wait_for(client.queue.get(), timeout=PING_INTERVAL)
        except TimeoutError:
            msg = {"type": "ping"}
        if msg.get("type") == "session_revoked":
            await ws.close(code=4401)
            return
        await ws.send_text(json.dumps(msg, separators=(",", ":")))


async def _session_checker(client: Client, organization_id: uuid.UUID) -> None:
    while True:
        await asyncio.sleep(SESSION_CHECK_INTERVAL)
        with tenant_scope(organization_id):
            async with sessionmaker()() as db:
                active = await auth_service.is_session_active(db, client.session_id)
        if not active:
            client.offer({"type": "session_revoked"})
            return
