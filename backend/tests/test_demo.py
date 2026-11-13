"""The demo hotel used for training and by the end-to-end tests in CI."""

from __future__ import annotations

from datetime import date

from app.demo import seed_demo
from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD, Api


async def test_seed_demo_fills_an_empty_hotel_once(admin: Api):
    summary = await seed_demo(ADMIN_EMAIL, ADMIN_PASSWORD, today=date(2026, 11, 13))
    assert summary.startswith("Demo hotel ready")
    types = {t["code"]: t for t in (await admin.get(admin.h("/room-types"))).json()}
    assert set(types) == {"STD-DBL", "DLX"}
    rooms = (await admin.get(admin.h("/rooms"))).json()
    numbers = sorted(r["number"] for r in rooms)
    assert numbers == [str(n) for n in range(101, 113)] + [str(n) for n in range(201, 207)]
    plans = {p["code"]: p for p in (await admin.get(admin.h("/rate-plans"))).json()}
    assert set(plans) == {"BAR", "NRF", "BB"} and plans["NRF"]["is_refundable"] is False
    rules = (await admin.get(admin.h("/pricing-rules"))).json()
    season = next(r for r in rules if r["kind"] == "season")
    assert (season["date_from"], season["date_to"]) == ("2026-12-15", "2027-01-15")
    # A quote works on the demo data (default plan, Standard Double).
    r = await admin.post(
        admin.h("/reservations/quote"),
        {
            "arrival": "2027-03-01",
            "departure": "2027-03-03",
            "rooms": [{"room_type_id": types["STD-DBL"]["id"]}],
        },
    )
    assert r.status_code == 200, r.text
    # Second run: nothing changes.
    assert "nothing changed" in await seed_demo(ADMIN_EMAIL, ADMIN_PASSWORD)
    assert len((await admin.get(admin.h("/rooms"))).json()) == 18
