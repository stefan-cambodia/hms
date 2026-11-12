"""Phase 8 — analytics. Every expected value below is computed by hand from
the fixture hotel, so the KPI formulas are checked, not just exercised."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from app.core.db import sessionmaker
from app.modules.reports.service import last_year, pct, previous_period
from tests.conftest import Api, error_code
from tests.test_restaurant import add, in_house_guest, open_check, pay, resto  # noqa: F401 (fixture)


def today() -> date:
    return datetime.now(ZoneInfo("Asia/Phnom_Penh")).date()


def d(offset: int) -> str:
    return (today() + timedelta(days=offset)).isoformat()


async def room_type(admin: Api, code: str, rooms: int, first: int) -> str:
    rt = (
        await admin.post(
            admin.h("/room-types"),
            {
                "code": code,
                "name": {"en": code},
                "base_occupancy": 2,
                "max_occupancy": 2,
                "max_adults": 2,
                "max_children": 0,
                "base_price": "50.00",
            },
        )
    ).json()
    r = await admin.post(
        admin.h("/rooms/bulk"), {"room_type_id": rt["id"], "start": first, "end": first + rooms - 1}
    )
    assert r.status_code == 201, r.text
    return rt["id"]


@pytest.fixture
async def hotel(admin: Api) -> dict:
    """Type A: 3 rooms at 100.00; type B: 2 rooms at 200.00 (explicit daily
    rates on the default plan for the next 30 nights)."""
    a = await room_type(admin, "A", 3, 101)
    b = await room_type(admin, "B", 2, 201)
    plans = (await admin.get(admin.h("/rate-plans"))).json()
    plan = next(p for p in plans if p["is_default"])
    for rt, price in ((a, "100.00"), (b, "200.00")):
        r = await admin.post(
            admin.h("/rates/bulk"),
            {
                "rate_plan_ids": [plan["id"]],
                "room_type_ids": [rt],
                "start": d(0),
                "end": d(30),
                "price": {"mode": "set", "value": price},
            },
        )
        assert r.status_code == 200, r.text
    rooms = {r["number"]: r["id"] for r in (await admin.get(admin.h("/rooms"))).json()}
    return {"a": a, "b": b, "plan": plan["id"], "rooms": rooms}


async def book(
    admin: Api, rt: str, arrival: int, departure: int, source: str = "direct", room_id: str | None = None
) -> dict:
    r = await admin.post(
        admin.h("/reservations"),
        {
            "arrival": d(arrival),
            "departure": d(departure),
            "guest": {"first_name": "Sok", "last_name": "Dara"},
            "rooms": [{"room_type_id": rt, "adults": 2, "room_id": room_id}],
            "source": source,
            "override_restrictions": True,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


async def performance(api: Api, start: int, end: int, **params) -> dict:
    r = await api.get(api.h("/reports/performance"), params={"start": d(start), "end": d(end), **params})
    assert r.status_code == 200, r.text
    return r.json()


async def scenario(admin: Api, hotel: dict) -> None:
    """Nights d10..d13 (window [d10, d14)):
    * R1: A, d10 → d12 (2 nights × 100), direct
    * R2: B, d11 → d14 (3 nights × 200), Booking.com
    * R3: A, d12 → d13, cancelled (releases its night)
    * room 101 (A) blocked d13 → d14 (1 room-night out of service)"""
    await book(admin, hotel["a"], 10, 12)
    await book(admin, hotel["b"], 11, 14, "booking_com")
    r3 = await book(admin, hotel["a"], 12, 13)
    r = await admin.post(
        admin.h(f"/reservations/{r3['id']}/cancel"), {"version": r3["version"], "reason": "Plans changed"}
    )
    assert r.status_code == 200, r.text
    r = await admin.post(
        admin.h("/room-blocks"), {"room_id": hotel["rooms"]["101"], "start_date": d(13), "end_date": d(14)}
    )
    assert r.status_code == 201, r.text


async def test_kpis_daily_and_breakdowns_match_hand_computed_values(admin: Api, hotel: dict):
    await scenario(admin, hotel)
    rep = await performance(admin, 10, 14)
    t = rep["totals"]
    # 5 rooms × 4 nights = 20; 1 blocked → 19 available; 2 + 3 nights sold.
    assert (t["rooms"], t["out_of_service"], t["available"], t["sold"]) == (20, 1, 19, 5)
    assert t["occupancy"] == "26.3"  # 5 / 19
    assert (t["revenue"], t["adr"], t["revpar"]) == ("800.00", "160.00", "42.11")  # 800/5, 800/19

    daily = {x["date"]: x for x in rep["daily"]}
    assert [
        (daily[d(i)]["sold"], daily[d(i)]["available"], daily[d(i)]["occupancy"]) for i in range(10, 14)
    ] == [
        (1, 5, "20.0"),
        (2, 5, "40.0"),
        (1, 5, "20.0"),  # R3 was cancelled
        (1, 4, "25.0"),  # one room out of service
    ]
    assert daily[d(11)]["adr"] == "150.00" and daily[d(11)]["revpar"] == "60.00"  # (100+200)/2, 300/5

    sources = {r["source"]: r for r in rep["by_source"]}
    assert (
        sources["booking_com"]["sold"],
        sources["booking_com"]["share"],
        sources["booking_com"]["revenue"],
    ) == (
        3,
        "60.0",
        "600.00",
    )
    assert (sources["direct"]["sold"], sources["direct"]["revenue_share"], sources["direct"]["adr"]) == (
        2,
        "25.0",
        "100.00",
    )
    types = {r["room_type_id"]: r for r in rep["by_room_type"]}
    a, b = types[hotel["a"]], types[hotel["b"]]
    assert (a["available"], a["sold"], a["occupancy"], a["adr"]) == (11, 2, "18.2", "100.00")
    assert (b["available"], b["sold"], b["occupancy"], b["adr"], b["revpar"]) == (
        8,
        3,
        "37.5",
        "200.00",
        "75.00",
    )
    [plan] = rep["by_rate_plan"]
    assert plan["rate_plan_id"] == hotel["plan"] and plan["sold"] == 5

    # Stays arriving in the window: R1 (2 nights) and R2 (3 nights), booked today.
    bk = rep["bookings"]
    assert (bk["arrivals"], bk["average_stay"], bk["average_lead_days"]) == (2, "2.5", "10.5")


async def test_cancellation_and_no_show_rates(admin: Api, hotel: dict):
    await scenario(admin, hotel)
    # Booking basis: 3 reservations created today, 1 cancelled.
    bk = (await performance(admin, 0, 1))["bookings"]
    assert (bk["created"], bk["cancelled"], bk["cancellation_rate"]) == (3, 1, "33.3")
    # A no-show among the arrivals of the window (status set as the night audit would).
    r4 = await book(admin, hotel["a"], 11, 12)
    async with sessionmaker()() as db:
        await db.execute(text("UPDATE reservations SET status = 'no_show' WHERE id = :id"), {"id": r4["id"]})
        await db.execute(
            text("UPDATE reservation_rooms SET occupies_inventory = false WHERE reservation_id = :id"),
            {"id": r4["id"]},
        )
        await db.commit()
    bk = (await performance(admin, 10, 14))["bookings"]
    assert (bk["arrivals"], bk["no_shows"], bk["no_show_rate"]) == (2, 1, "33.3")  # 1 / (2 + 1)


async def test_empty_period_gives_null_ratios_and_comparisons(admin: Api, hotel: dict):
    await scenario(admin, hotel)
    rep = await performance(admin, 10, 14, compare="previous")
    c = rep["compare"]
    assert (c["kind"], c["start"], c["end"]) == ("previous", d(6), d(10))
    assert c["totals"]["sold"] == 0 and c["totals"]["occupancy"] == "0.0"
    assert c["totals"]["adr"] is None  # nothing sold: no average, not a misleading 0
    assert len(c["daily"]) == 4
    ly = (await performance(admin, 10, 14, compare="last_year"))["compare"]
    assert ly["totals"]["available"] == 0 and ly["totals"]["occupancy"] is None  # rooms did not exist yet
    # Date arithmetic.
    assert previous_period(date(2026, 3, 1), date(2026, 3, 8)) == (date(2026, 2, 22), date(2026, 3, 1))
    assert last_year(date(2028, 2, 29), date(2028, 3, 1)) == (date(2027, 2, 28), date(2027, 3, 1))
    assert pct(1, 3) == Decimal("33.3") and pct(0, 0) is None
    r = await admin.get(admin.h("/reports/performance"), params={"start": d(5), "end": d(5)})
    assert r.status_code == 422 and error_code(r) == "INVALID_RANGE"


async def test_revenue_is_reserved_to_financial_reports(admin: Api, hotel: dict, user_factory):
    await scenario(admin, hotel)
    manager = await user_factory("reservation_manager")  # reports.view, not reports.financial
    rep = await performance(manager, 10, 14)
    assert rep["financial"] is False and rep["totals"]["occupancy"] == "26.3"
    assert (
        rep["totals"]["revenue"] is None and rep["totals"]["adr"] is None and rep["totals"]["revpar"] is None
    )
    assert all(r["revenue"] is None for r in rep["by_source"]) and rep["other_revenue"] is None
    accountant = await user_factory("accountant")
    assert (await performance(accountant, 10, 14))["totals"]["adr"] == "160.00"
    clerk = await user_factory("housekeeping")
    assert (
        await clerk.get(clerk.h("/reports/performance"), params={"start": d(0), "end": d(1)})
    ).status_code == 403


async def test_other_revenue_counts_room_charges_once(admin: Api, resto):  # noqa: F811
    guest = await in_house_guest(admin)
    # Folio service 15.00 (VAT 10 % added on top: 1.50 not counted).
    r = await admin.post(
        admin.h(f"/reservations/{guest['id']}/charges"),
        {"kind": "service", "description": "Airport transfer", "unit_price": "15.00"},
    )
    assert r.status_code == 201, r.text
    # A check paid in cash: 8.00 + 10 % service = 8.80 before VAT.
    order = await add(admin, resto, await open_check(admin, resto), ("amok", 1))
    await admin.post(admin.h(f"/restaurant/orders/{order['id']}/send"))
    assert (await pay(admin, order, method="cash", amount="20.00")).status_code == 201
    # A check charged to the room: 2 × 2.50 + 10 % = 5.50 before VAT; it also
    # appears on the folio as an "outlet" line, which must not be counted again.
    order = await add(admin, resto, await open_check(admin, resto, "T2"), ("beer", 2))
    await admin.post(admin.h(f"/restaurant/orders/{order['id']}/send"))
    r = await pay(admin, order, method="room_charge", reservation_room_id=guest["rooms"][0]["id"])
    assert r.status_code == 201, r.text

    rep = await performance(admin, -1, 1)
    other = rep["other_revenue"]
    assert (other["services"], other["restaurant"], other["restaurant_checks"]) == ("15.00", "14.30", 2)
    assert other["total"] == "29.30"
    # The in-house guest's nights are room revenue (40.00 base price, nights d-1 and d0).
    assert rep["totals"]["sold"] == 2 and rep["totals"]["revenue"] == "80.00"


async def test_forecast_pickup_and_dashboard(admin: Api, hotel: dict, user_factory):
    await scenario(admin, hotel)
    guest = await book(admin, hotel["a"], 0, 2, room_id=hotel["rooms"]["102"])
    r = await admin.post(
        admin.h(f"/reservations/{guest['id']}/check-in"),
        {"version": guest["version"], "ignore_room_status": True},
    )
    assert r.status_code == 200, r.text
    await book(admin, hotel["b"], 0, 1)  # arrival due today

    fc = (await admin.get(admin.h("/reports/forecast"), params={"days": 20})).json()
    assert fc["start"] == d(0) and len(fc["daily"]) == 20
    # Booked today, so everything on the books was picked up in the last 7 days.
    assert fc["totals"]["sold"] == fc["totals"]["pickup"] == 2 + 1 + 2 + 3
    day = {x["date"]: x for x in fc["daily"]}
    assert (day[d(0)]["sold"], day[d(0)]["occupancy"]) == (2, "40.0")

    t = (await admin.get(admin.h("/reports/today"))).json()
    assert t["date"] == d(0)
    assert (t["arrivals_due"], t["arrived"], t["in_house"], t["departures_due"]) == (1, 1, 1, 0)
    assert (t["tonight"]["sold"], t["tonight"]["available"], t["tonight"]["occupancy"]) == (2, 5, "40.0")
    assert t["tonight"]["revenue"] == "300.00" and len(t["next_days"]) == 14
    assert t["month_to_date_last_year"]["available"] == 0
    # Front desk staff see the movements but not the revenue.
    clerk = await user_factory("receptionist")
    t = (await clerk.get(clerk.h("/reports/today"))).json()
    assert t["in_house"] == 1 and t["tonight"]["occupancy"] == "40.0" and t["tonight"]["revenue"] is None
