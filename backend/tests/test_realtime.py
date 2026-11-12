"""Real-time synchronisation, end to end: a live uvicorn server, a real
PostgreSQL LISTEN connection and real WebSocket clients."""

from __future__ import annotations

import asyncio
import json
import socket

import httpx
import pytest
import uvicorn
import websockets
from websockets.exceptions import ConnectionClosed

from app.core import events
from app.core.db import sessionmaker
from app.main import create_app
from app.modules.realtime.hub import hub
from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
async def server(installation):
    port = _free_port()
    srv = uvicorn.Server(
        uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning", lifespan="on")
    )
    task = asyncio.create_task(srv.serve())
    for _ in range(200):
        if srv.started and hub.listening.is_set():
            break
        await asyncio.sleep(0.05)
    assert hub.listening.is_set()
    yield f"127.0.0.1:{port}"
    srv.should_exit = True
    await task


async def _token(base: str, email: str, password: str) -> str:
    async with httpx.AsyncClient(base_url=f"http://{base}") as c:
        r = await c.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
            headers={"X-Auth-Mode": "bearer"},
        )
        assert r.status_code == 200, r.text
        return r.json()["token"]


async def _subscribe(base: str, token: str, hotel_id: str):
    ws = await websockets.connect(f"ws://{base}/api/v1/ws")
    await ws.send(json.dumps({"type": "auth", "token": token}))
    await ws.send(json.dumps({"type": "subscribe", "hotel_id": hotel_id}))
    ready = json.loads(await asyncio.wait_for(ws.recv(), 5))
    assert ready == {"type": "ready", "hotel_id": hotel_id}
    return ws


async def _next_event(ws, timeout: float = 5) -> dict:
    while True:
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout))
        if msg["type"] != "ping":
            return msg


async def _api(base: str, token: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=f"http://{base}", headers={"Authorization": f"Bearer {token}"})


async def test_change_on_one_device_reaches_another(server, installation):
    token = await _token(server, ADMIN_EMAIL, ADMIN_PASSWORD)
    tablet = await _subscribe(server, token, installation.hotel_id)
    desktop = await _subscribe(server, token, installation.hotel_id)
    async with await _api(server, token) as api:
        r = await api.post(
            f"/api/v1/hotels/{installation.hotel_id}/buildings", json={"code": "A", "name": "Main"}
        )
        assert r.status_code == 201
    for ws in (tablet, desktop):
        event = await _next_event(ws)
        assert event["type"] == "event"
        assert event["entity"] == "building" and event["action"] == "created"
        assert event["id"] == r.json()["id"] and event["hotel_id"] == installation.hotel_id
        await ws.close()


async def test_rolled_back_changes_are_never_announced(server, installation):
    token = await _token(server, ADMIN_EMAIL, ADMIN_PASSWORD)
    ws = await _subscribe(server, token, installation.hotel_id)
    async with sessionmaker()() as db:
        await events.emit(
            db, hotel_id=installation.hotel_id, entity="room", action="updated", entity_id="rolled-back"
        )
        await db.rollback()
        await events.emit(
            db, hotel_id=installation.hotel_id, entity="room", action="updated", entity_id="committed"
        )
        await db.commit()
    event = await _next_event(ws)
    assert event["id"] == "committed"
    await ws.close()


async def test_cannot_subscribe_to_foreign_hotel(server, installation):
    token = await _token(server, ADMIN_EMAIL, ADMIN_PASSWORD)
    ws = await websockets.connect(f"ws://{server}/api/v1/ws")
    await ws.send(json.dumps({"type": "auth", "token": token}))
    await ws.send(json.dumps({"type": "subscribe", "hotel_id": "00000000-0000-0000-0000-000000000000"}))
    with pytest.raises(ConnectionClosed) as exc:
        await asyncio.wait_for(ws.recv(), 5)
    assert exc.value.rcvd.code == 4403


async def test_bad_token_and_cross_site_origin_rejected(server):
    ws = await websockets.connect(f"ws://{server}/api/v1/ws")
    await ws.send(json.dumps({"type": "auth", "token": "invalid"}))
    with pytest.raises(ConnectionClosed) as exc:
        await asyncio.wait_for(ws.recv(), 5)
    assert exc.value.rcvd.code == 4401
    with pytest.raises(Exception):  # noqa: B017 - handshake rejected (close before accept)
        async with websockets.connect(f"ws://{server}/api/v1/ws", origin="https://evil.example") as ws:
            await asyncio.wait_for(ws.recv(), 5)


async def test_events_filtered_by_permission(server, installation):
    admin_token = await _token(server, ADMIN_EMAIL, ADMIN_PASSWORD)
    async with await _api(server, admin_token) as api:
        roles = (await api.get(f"/api/v1/hotels/{installation.hotel_id}/roles")).json()
        hk = next(r["id"] for r in roles if r["code"] == "housekeeping")
        r = await api.post(
            f"/api/v1/hotels/{installation.hotel_id}/users",
            json={
                "email": "hk@example.com",
                "full_name": "HK",
                "password": "Str0ng-Passw0rd",
                "role_ids": [hk],
            },
        )
        assert r.status_code == 201
        hk_ws = await _subscribe(
            server, await _token(server, "hk@example.com", "Str0ng-Passw0rd"), installation.hotel_id
        )
        # A user event (needs users.view) must not reach housekeeping...
        await api.post(
            f"/api/v1/hotels/{installation.hotel_id}/users",
            json={"email": "x@example.com", "full_name": "X", "password": "Str0ng-Passw0rd", "role_ids": []},
        )
        # ...but a building event (hotel.view) must.
        await api.post(f"/api/v1/hotels/{installation.hotel_id}/buildings", json={"code": "B", "name": "B"})
    event = await _next_event(hk_ws)
    assert event["entity"] == "building"
    await hk_ws.close()


async def test_revoked_session_socket_is_closed(server, installation):
    admin_token = await _token(server, ADMIN_EMAIL, ADMIN_PASSWORD)
    async with await _api(server, admin_token) as api:
        victim_token = await _token(server, ADMIN_EMAIL, ADMIN_PASSWORD)
        ws = await _subscribe(server, victim_token, installation.hotel_id)
        sessions = (await api.get(f"/api/v1/hotels/{installation.hotel_id}/sessions")).json()
        me = (await api.get("/api/v1/auth/me")).json()["session_id"]
        victim = next(s for s in sessions if s["id"] != me)
        r = await api.delete(f"/api/v1/hotels/{installation.hotel_id}/sessions/{victim['id']}")
        assert r.status_code == 204
    with pytest.raises(ConnectionClosed) as exc:
        while True:
            await asyncio.wait_for(ws.recv(), 5)
    assert exc.value.rcvd.code == 4401
