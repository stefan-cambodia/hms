"""Demo hotel content ("Lotus Riverside Hotel"), for demonstrations, training
and the end-to-end tests in CI.

It goes through the public API (in-process, without a running server), so
the demo data passes exactly the validations a user's input passes. It only
fills an empty hotel: if room categories already exist, nothing is changed.
No reservation is created: the tests and the trainer create their own.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx

from app.main import create_app


class SeedError(RuntimeError):
    pass


async def _call(client: httpx.AsyncClient, method: str, path: str, body: Any = None) -> Any:
    r = await client.request(method, path, json=body)
    if r.status_code >= 400:
        raise SeedError(f"{method} {path}: {r.status_code} {r.text}")
    return r.json() if r.content else None


async def seed_demo(email: str, password: str, today: date | None = None) -> str:
    """Fill the admin's first hotel. Returns a one-line summary."""
    today = today or date.today()
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        r = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
        if r.status_code != 200:
            raise SeedError(f"login failed: {r.status_code} {r.text}")
        me = r.json()
        client.headers["X-CSRF-Token"] = me["csrf_token"]
        hotel_id = me["hotels"][0]["id"]

        def h(p: str) -> str:
            return f"/api/v1/hotels/{hotel_id}{p}"

        if await _call(client, "GET", h("/room-types")):
            return "The hotel already has room categories: nothing changed."

        hotel = await _call(client, "GET", h(""))
        await _call(
            client,
            "PATCH",
            h(""),
            {
                "version": hotel["version"],
                "address_line1": "12 Sisowath Quay",
                "city": "Phnom Penh",
                "country_code": "KH",
                "phone": "+855 23 900 100",
            },
        )
        building = await _call(client, "POST", h("/buildings"), {"code": "MAIN", "name": "Main building"})
        floors = [
            await _call(
                client, "POST", h("/floors"), {"building_id": building["id"], "level": level, "name": name}
            )
            for level, name in ((1, "First floor"), (2, "Second floor"))
        ]
        std = await _call(
            client,
            "POST",
            h("/room-types"),
            {
                "code": "STD-DBL",
                "name": {"en": "Standard Double", "fr": "Chambre double standard", "km": "បន្ទប់ពីរនាក់ធម្មតា"},
                "base_occupancy": 2,
                "max_occupancy": 3,
                "max_adults": 2,
                "max_children": 1,
                "base_price": "45.00",
                "sort_order": 1,
            },
        )
        dlx = await _call(
            client,
            "POST",
            h("/room-types"),
            {
                "code": "DLX",
                "name": {
                    "en": "Deluxe River View",
                    "fr": "Deluxe vue sur le fleuve",
                    "km": "បន្ទប់ពិសេសមើលទន្លេ",
                },
                "base_occupancy": 2,
                "max_occupancy": 3,
                "max_adults": 3,
                "max_children": 1,
                "base_price": "85.00",
                "sort_order": 2,
            },
        )
        for rt, floor, start, end in ((std, floors[0], 101, 112), (dlx, floors[1], 201, 206)):
            await _call(
                client,
                "POST",
                h("/rooms/bulk"),
                {
                    "room_type_id": rt["id"],
                    "building_id": building["id"],
                    "floor_id": floor["id"],
                    "start": start,
                    "end": end,
                },
            )
        # The installation already has standard policies; create only what is missing.
        policies = {p["code"]: p for p in await _call(client, "GET", h("/cancellation-policies"))}
        wanted = {
            "FLEX": {
                "name": {"en": "Flexible"},
                "free_until_days": 1,
                "penalty_kind": "nights",
                "penalty_value": "1",
            },
            "NONREF": {"name": {"en": "Non-refundable"}, "penalty_kind": "percent", "penalty_value": "100"},
        }
        for code, body in wanted.items():
            if code not in policies:
                policies[code] = await _call(
                    client, "POST", h("/cancellation-policies"), {"code": code, **body}
                )
        flex, nonref = policies["FLEX"], policies["NONREF"]
        plans = await _call(client, "GET", h("/rate-plans"))
        bar = next(p for p in plans if p["is_default"])
        await _call(
            client,
            "PATCH",
            h(f"/rate-plans/{bar['id']}"),
            {"version": bar["version"], "cancellation_policy_id": flex["id"]},
        )
        await _call(
            client,
            "POST",
            h("/rate-plans"),
            {
                "code": "NRF",
                "name": {"en": "Non-refundable saver"},
                "is_refundable": False,
                "cancellation_policy_id": nonref["id"],
                "parent_rate_plan_id": bar["id"],
                "derive_mode": "percent",
                "derive_value": "-10",
                "sort_order": 1,
            },
        )
        await _call(
            client,
            "POST",
            h("/rate-plans"),
            {
                "code": "BB",
                "name": {"en": "Bed & breakfast"},
                "meal_plan": "breakfast",
                "cancellation_policy_id": flex["id"],
                "parent_rate_plan_id": bar["id"],
                "derive_mode": "amount_per_person",
                "derive_value": "8",
                "sort_order": 2,
            },
        )
        rules = [
            {
                "name": {"en": "High season"},
                "kind": "season",
                "date_from": f"{today.year}-12-15",
                "date_to": f"{today.year + 1}-01-15",
                "adjustment": "percent",
                "value": "30",
            },
            {
                "name": {"en": "Weekend nights"},
                "kind": "weekday",
                "weekdays": [4, 5],
                "adjustment": "percent",
                "value": "15",
            },
            {
                "name": {"en": "Stay 7, save 10%"},
                "kind": "long_stay",
                "adjustment": "percent",
                "value": "-10",
                "conditions": {"min_nights": 7},
            },
            {
                "name": {"en": "Last-minute deal"},
                "kind": "last_minute",
                "adjustment": "percent",
                "value": "-15",
                "conditions": {"max_days_before": 2},
            },
        ]
        for rule in rules:
            await _call(client, "POST", h("/pricing-rules"), rule)
        await _call(
            client,
            "POST",
            h("/tax-rates"),
            {
                "code": "VAT",
                "name": {"en": "VAT", "fr": "TVA"},
                "kind": "percent",
                "rate": "10",
                "applies_to": "all",
            },
        )
        await _call(
            client,
            "POST",
            h("/facilities"),
            {
                "code": "POOL",
                "category": "pool",
                "name": {"en": "Riverside pool", "fr": "Piscine au bord du fleuve"},
            },
        )
    return "Demo hotel ready: 18 rooms in 2 categories, 3 rate plans, 4 pricing rules, VAT 10 %, a pool."
