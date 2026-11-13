"""Load test against a running HMS server (phase 10).

    python loadtest/run.py --base https://localhost:18443 --email admin@hotel.local \
        --password ... [--staff 30] [--minutes 5] [--rooms 120] [--history 1500] [--insecure]

Three measurements, written to a JSON file and printed as a Markdown report:

1. Front desk mix: N staff sessions, each looping over the screens a hotel
   team really uses (dashboard, front desk, room board, calendar, availability
   search, reservation search and detail, guest search, housekeeping) and
   creating / cancelling reservations, with 0.5-2 s pauses between actions.
   Latency per operation (p50/p95/p99/max), throughput and errors.
2. Contention: many simultaneous bookings for the last rooms of one category
   on the same night. Exactly as many succeed as there are rooms; the others
   are refused; no room is allocated twice.
3. Real-time fan-out: devices connected over WebSocket; one change; time
   until every device has received the event.

The hotel is prepared through the API (rooms of a load-test category,
`--history` past and future reservations), so the database has realistic
volume. Run it on a test installation, never on a hotel in service.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import random
import ssl
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx
import websockets

API = "/api/v1"


@dataclass
class Stats:
    latencies: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    errors: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    # Requests over 1 s, with when they started (seconds into the run), to
    # tell a slow operation from a moment where everything was slow.
    slow: list[tuple[float, str, float]] = field(default_factory=list)
    origin: float = field(default_factory=time.monotonic)

    def add(self, name: str, seconds: float, error: str | None = None) -> None:
        self.latencies[name].append(seconds * 1000)
        if error:
            self.errors[name].append(error)
        if seconds > 1:
            started = time.monotonic() - seconds - self.origin
            self.slow.append((round(started, 1), name, round(seconds * 1000)))

    def summary(self, duration: float) -> dict[str, Any]:
        out: dict[str, Any] = {}
        total = 0
        for name, values in sorted(self.latencies.items()):
            values.sort()
            total += len(values)
            out[name] = {
                "count": len(values),
                "errors": len(self.errors.get(name, [])),
                "p50_ms": round(pct(values, 50), 1),
                "p95_ms": round(pct(values, 95), 1),
                "p99_ms": round(pct(values, 99), 1),
                "max_ms": round(values[-1], 1),
            }
        errors = {name: sorted(set(codes)) for name, codes in self.errors.items()}
        return {
            "operations": out,
            "requests": total,
            "throughput_rps": round(total / duration, 1),
            "error_statuses": errors,
            "slow_requests": sorted(self.slow),
        }


def pct(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)


class Session:
    def __init__(self, base: str, verify: bool | ssl.SSLContext) -> None:
        self.client = httpx.AsyncClient(base_url=base + API, verify=verify, timeout=60)
        self.hotel = ""
        self.csrf = ""

    async def login(self, email: str, password: str) -> dict:
        for _ in range(10):
            r = await self.client.post("/auth/login", json={"email": email, "password": password})
            if r.status_code == 429:
                # Per-IP sign-in throttling (refused attempts count too): wait
                # for the window to pass instead of hammering it.
                await asyncio.sleep(61)
                continue
            r.raise_for_status()
            me = r.json()
            self.csrf = me["csrf_token"]
            self.client.headers["X-CSRF-Token"] = self.csrf
            self.hotel = me["hotels"][0]["id"]
            return me
        raise RuntimeError("login throttled for too long")

    def h(self, path: str) -> str:
        return f"/hotels/{self.hotel}{path}"

    async def timed(
        self, stats: Stats | None, name: str, method: str, path: str, **kw: Any
    ) -> httpx.Response:
        ok_statuses = kw.pop("_ok", ())
        t0 = time.perf_counter()
        try:
            r = await self.client.request(method, path, **kw)
        except httpx.HTTPError as exc:
            if stats:
                stats.add(name, time.perf_counter() - t0, type(exc).__name__)
            raise
        if stats:
            error = None if r.status_code < 400 or r.status_code in ok_statuses else str(r.status_code)
            stats.add(name, time.perf_counter() - t0, error)
        return r

    async def close(self) -> None:
        await self.client.aclose()


# --- Preparation -------------------------------------------------------------


async def prepare(admin: Session, rooms: int, history: int, staff: int, password: str) -> dict[str, Any]:
    """A load-test room category with `rooms` rooms, `history` reservations
    spread over the past 60 and next 120 days, and `staff` front-desk users."""
    types = (await admin.client.get(admin.h("/room-types"))).json()
    rt = next((t for t in types if t["code"] == "LOAD"), None)
    if rt is None:
        r = await admin.client.post(
            admin.h("/room-types"),
            json={
                "code": "LOAD",
                "name": {"en": "Load test room"},
                "base_occupancy": 2,
                "max_occupancy": 3,
                "max_adults": 3,
                "max_children": 1,
                "base_price": "50.00",
            },
        )
        r.raise_for_status()
        rt = r.json()
    existing = [
        x for x in (await admin.client.get(admin.h("/rooms"))).json() if x["room_type_id"] == rt["id"]
    ]
    for i in range(len(existing), rooms):
        r = await admin.client.post(
            admin.h("/rooms"), json={"room_type_id": rt["id"], "number": f"L{i + 1:03d}"}
        )
        r.raise_for_status()
    today = date.today()
    made = 0
    sem = asyncio.Semaphore(8)

    async def one(i: int) -> None:
        nonlocal made
        arrival = today + timedelta(days=random.randint(-60, 120))
        nights = random.choice((1, 1, 2, 2, 3, 4, 7))
        async with sem:
            r = await admin.client.post(
                admin.h("/reservations"),
                json={
                    "arrival": arrival.isoformat(),
                    "departure": (arrival + timedelta(days=nights)).isoformat(),
                    "guest": {"first_name": f"Load{i}", "last_name": random.choice(NAMES)},
                    "rooms": [{"room_type_id": rt["id"], "adults": random.choice((1, 2, 2))}],
                    "source": random.choice(("direct", "phone", "walk_in", "booking_com", "agoda")),
                },
                headers={"Idempotency-Key": f"load-history-{i}"},
            )
            if r.status_code in (200, 201):
                made += 1

    await asyncio.gather(*(one(i) for i in range(history)))
    roles = (await admin.client.get(admin.h("/roles"))).json()
    receptionist = next(r["id"] for r in roles if r["code"] == "receptionist")
    manager = next(r["id"] for r in roles if r["code"] == "manager")
    users = {u["email"] for u in (await admin.client.get(admin.h("/users"))).json()}
    emails = []
    managers = max(1, staff // 6)  # one manager for five receptionists
    for i in range(staff):
        email = f"load{i:02d}@loadtest.local"
        emails.append(email)
        if email not in users:
            r = await admin.client.post(
                admin.h("/users"),
                json={
                    "email": email,
                    "full_name": f"Load {i:02d}",
                    "password": password,
                    "role_ids": [manager if i < managers else receptionist],
                },
            )
            r.raise_for_status()
    return {
        "room_type_id": rt["id"],
        "rooms": rooms,
        "history_created": made,
        "staff": emails,
        "managers": managers,
    }


NAMES = ("Chan", "Sok", "Dupont", "Martin", "Ivanova", "Wang", "Li", "Smith", "Nguyen", "Kim", "Garcia")


# --- 1. Front desk mix -------------------------------------------------------


async def staff_loop(s: Session, stats: Stats, room_type_id: str, until: float, manager: bool) -> None:
    today = date.today()
    mine: list[dict] = []
    while time.monotonic() < until:
        d = today + timedelta(days=random.randint(0, 30))
        roll = random.random()
        try:
            if roll < 0.10:
                await s.timed(stats, "dashboard (reports/today)", "GET", s.h("/reports/today"))
            elif roll < 0.20:
                await s.timed(stats, "front desk", "GET", s.h("/front-desk"))
            elif roll < 0.30:
                await s.timed(stats, "room board", "GET", s.h("/room-board"))
            elif roll < 0.42:
                start = today + timedelta(days=random.randint(-3, 20))
                await s.timed(
                    stats,
                    "calendar 14 days",
                    "GET",
                    s.h("/calendar"),
                    params={"start": start.isoformat(), "end": (start + timedelta(days=14)).isoformat()},
                )
            elif roll < 0.54:
                await s.timed(
                    stats,
                    "availability search",
                    "GET",
                    s.h("/availability"),
                    params={"start": d.isoformat(), "end": (d + timedelta(days=3)).isoformat()},
                )
            elif roll < 0.62:
                await s.timed(
                    stats,
                    "reservation search",
                    "GET",
                    s.h("/reservations"),
                    params={"q": random.choice(NAMES), "limit": 50},
                )
            elif roll < 0.68:
                await s.timed(
                    stats, "guest search", "GET", s.h("/guests"), params={"q": random.choice(NAMES)}
                )
            elif roll < 0.73:
                await s.timed(stats, "housekeeping tasks", "GET", s.h("/housekeeping/tasks"))
            elif roll < 0.76 and manager:  # reports need reports.view
                start = today - timedelta(days=30)
                await s.timed(
                    stats,
                    "performance report 30 days",
                    "GET",
                    s.h("/reports/performance"),
                    params={"start": start.isoformat(), "end": today.isoformat()},
                )
            elif roll < 0.90 or not mine:
                r = await s.timed(
                    stats,
                    "create reservation",
                    "POST",
                    s.h("/reservations"),
                    json={
                        "arrival": d.isoformat(),
                        "departure": (d + timedelta(days=random.choice((1, 2, 3)))).isoformat(),
                        "guest": {"first_name": "Walk", "last_name": random.choice(NAMES)},
                        "rooms": [{"room_type_id": room_type_id, "adults": 2}],
                        "source": "phone",
                    },
                    headers={"Idempotency-Key": str(uuid.uuid4())},
                    # Sold out on that date is a correct answer, not an error.
                    _ok=(409, 422),
                )
                if r.status_code == 201:
                    mine.append(r.json())
                    await s.timed(stats, "reservation detail", "GET", s.h(f"/reservations/{r.json()['id']}"))
            else:
                res = mine.pop(random.randrange(len(mine)))
                await s.timed(
                    stats,
                    "cancel reservation",
                    "POST",
                    s.h(f"/reservations/{res['id']}/cancel"),
                    json={"version": res["version"], "reason": "load test", "waive_fee": False},
                )
        except httpx.HTTPError:
            pass
        await asyncio.sleep(random.uniform(0.5, 2.0))


# --- 2. Contention -----------------------------------------------------------


async def contention(sessions: list[Session], admin: Session, attempts: int) -> dict[str, Any]:
    """`attempts` simultaneous bookings for one night far in the future, in a
    fresh category of 3 rooms: exactly 3 must succeed."""
    code = "C" + uuid.uuid4().hex[:6].upper()
    rt = (
        await admin.client.post(
            admin.h("/room-types"),
            json={
                "code": code,
                "name": {"en": "Contention"},
                "base_occupancy": 2,
                "max_occupancy": 2,
                "max_adults": 2,
                "max_children": 0,
                "base_price": "40.00",
            },
        )
    ).json()
    for i in range(3):
        (
            await admin.client.post(
                admin.h("/rooms"), json={"room_type_id": rt["id"], "number": f"{code}-{i}"}
            )
        ).raise_for_status()
    night = date.today() + timedelta(days=200)
    body = {
        "arrival": night.isoformat(),
        "departure": (night + timedelta(days=1)).isoformat(),
        "guest": {"first_name": "Race", "last_name": "Test"},
        "rooms": [{"room_type_id": rt["id"], "adults": 1}],
    }

    async def book(i: int) -> int:
        s = sessions[i % len(sessions)]
        r = await s.client.post(
            s.h("/reservations"), json=body, headers={"Idempotency-Key": str(uuid.uuid4())}
        )
        return r.status_code

    t0 = time.perf_counter()
    codes = await asyncio.gather(*(book(i) for i in range(attempts)))
    elapsed = time.perf_counter() - t0
    avail = (
        await admin.client.get(
            admin.h("/availability"),
            params={"start": night.isoformat(), "end": (night + timedelta(days=1)).isoformat()},
        )
    ).json()
    left = next(a for a in avail if a["room_type_id"] == rt["id"])["nights"][0]["available"]
    by_code: dict[str, int] = defaultdict(int)
    for c in codes:
        by_code[str(c)] += 1
    return {
        "attempts": attempts,
        "rooms": 3,
        "status_codes": dict(by_code),
        "available_after": left,
        "seconds": round(elapsed, 2),
        "ok": by_code.get("201", 0) == 3 and left == 0,
    }


# --- 3. Real-time fan-out ----------------------------------------------------


async def fanout(
    base: str, sessions: list[Session], admin: Session, devices: int, ssl_ctx: Any
) -> dict[str, Any]:
    ws_base = base.replace("https://", "wss://").replace("http://", "ws://") + API + "/ws"
    ready = asyncio.Event()
    received: list[float] = []
    marker = f"FANOUT-{uuid.uuid4().hex[:8]}"
    connected = 0
    sent_at: list[float] = []

    async def device(i: int) -> None:
        nonlocal connected
        s = sessions[i % len(sessions)]
        cookie = "; ".join(f"{k}={v}" for k, v in s.client.cookies.items())
        origin = base
        async with websockets.connect(
            ws_base,
            additional_headers={"Cookie": cookie, "Origin": origin},
            ssl=ssl_ctx if ws_base.startswith("wss") else None,
        ) as ws:
            await ws.send(json.dumps({"type": "subscribe", "hotel_id": s.hotel}))
            while json.loads(await ws.recv()).get("type") != "ready":
                pass
            connected += 1
            if connected == devices:
                ready.set()
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
                if msg.get("type") == "event" and msg.get("entity") == "building":
                    received.append(time.perf_counter())
                    return
                if msg.get("type") == "ping":
                    await ws.send(json.dumps({"type": "pong"}))

    tasks = [asyncio.create_task(device(i)) for i in range(devices)]
    await asyncio.wait_for(ready.wait(), timeout=60)
    sent_at.append(time.perf_counter())
    r = await admin.client.post(admin.h("/buildings"), json={"code": marker[:20], "name": marker})
    r.raise_for_status()
    done, pending = await asyncio.wait(tasks, timeout=30)
    for t in pending:
        t.cancel()
    delays = sorted((t - sent_at[0]) * 1000 for t in received)
    return {
        "devices": devices,
        "received": len(received),
        "p50_ms": round(pct(delays, 50), 1),
        "p95_ms": round(pct(delays, 95), 1),
        "max_ms": round(delays[-1], 1) if delays else None,
        "note": "from sending the change (request included) to delivery on each device",
    }


# --- Main ----------------------------------------------------------------------


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--base", required=True)
    p.add_argument("--email", required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--staff", type=int, default=30)
    p.add_argument("--minutes", type=float, default=5)
    p.add_argument("--rooms", type=int, default=120)
    p.add_argument("--history", type=int, default=1500)
    p.add_argument("--race", type=int, default=50)
    p.add_argument("--devices", type=int, default=60)
    p.add_argument("--insecure", action="store_true", help="accept the server's certificate (local CA)")
    p.add_argument("--out", default="loadtest-result.json")
    args = p.parse_args()
    ssl_ctx: Any = True
    if args.insecure:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
    staff_password = "Load-Staff-2026"

    admin = Session(args.base, ssl_ctx)
    await admin.login(args.email, args.password)
    print("preparing the hotel…", flush=True)
    t0 = time.monotonic()
    prep = await prepare(admin, args.rooms, args.history, args.staff, staff_password)
    prep["seconds"] = round(time.monotonic() - t0, 1)
    print(
        f"  {prep['rooms']} load-test rooms, {prep['history_created']} reservations, {len(prep['staff'])} staff",
        flush=True,
    )

    sessions = [Session(args.base, ssl_ctx) for _ in prep["staff"]]
    # Every session comes from this one machine: stay under the per-IP
    # sign-in limit (20 per minute by default), as staff arriving would.
    print(f"signing in {len(sessions)} staff (one every 3.5 s)…", flush=True)
    for s, email in zip(sessions, prep["staff"], strict=True):
        await s.login(email, staff_password)
        await asyncio.sleep(3.5)

    print(f"front desk mix: {len(sessions)} staff for {args.minutes} min…", flush=True)
    stats = Stats()
    until = time.monotonic() + args.minutes * 60
    started, wall = time.monotonic(), time.time()
    stats.origin = started
    await asyncio.gather(
        *(
            staff_loop(s, stats, prep["room_type_id"], until, manager=i < prep["managers"])
            for i, s in enumerate(sessions)
        )
    )
    elapsed = time.monotonic() - started
    mix = stats.summary(elapsed)
    # The monotonic clock stops while the computer sleeps, the wall clock
    # does not: a difference means the measurement was interrupted.
    mix["host_paused_seconds"] = round(max(0.0, time.time() - wall - elapsed), 1)
    if mix["host_paused_seconds"] > 2:
        print(
            f"WARNING: the machine paused for {mix['host_paused_seconds']} s: results not valid", flush=True
        )

    print("contention…", flush=True)
    race = await contention(sessions, admin, args.race)
    print("real-time fan-out…", flush=True)
    rt = await fanout(args.base, sessions, admin, args.devices, ssl_ctx)

    result = {
        "machine": {"platform": platform.platform(), "python": platform.python_version()},
        "settings": vars(args) | {"password": "***"},
        "preparation": {k: v for k, v in prep.items() if k != "staff"},
        "front_desk_mix": mix,
        "contention": race,
        "realtime": rt,
    }
    Path(args.out).write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    for s in [admin, *sessions]:
        await s.close()


if __name__ == "__main__":
    asyncio.run(main())
