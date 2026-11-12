"""Rate plans, seasonal pricing, discounts, restrictions and the rate grid."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from tests.conftest import Api, error_code


def hotel_today() -> date:
    return datetime.now(ZoneInfo("Asia/Phnom_Penh")).date()


def next_weekday(start: date, weekday: int) -> date:
    return start + timedelta(days=(weekday - start.weekday()) % 7)


# A Monday ~2 months ahead: easy to reason about weekdays.
MON = next_weekday(hotel_today() + timedelta(days=60), 0)


def iso(d: date, offset: int = 0) -> str:
    return (d + timedelta(days=offset)).isoformat()


@pytest.fixture
async def setup(admin: Api) -> dict:
    rt = (
        await admin.post(
            admin.h("/room-types"),
            {
                "code": "STD",
                "name": {"en": "Standard"},
                "base_occupancy": 2,
                "max_occupancy": 3,
                "max_adults": 3,
                "max_children": 1,
                "base_price": "100.00",
                "extra_adult_price": "20.00",
            },
        )
    ).json()
    rooms = (
        await admin.post(admin.h("/rooms/bulk"), {"room_type_id": rt["id"], "start": 101, "end": 103})
    ).json()
    plans = (await admin.get(admin.h("/rate-plans"))).json()
    bar = next(p for p in plans if p["is_default"])
    return {"rt": rt["id"], "rooms": [r["id"] for r in rooms], "bar": bar["id"]}


async def quote(
    api: Api, s: dict, arrival: date, nights: int, plan: str | None = None, adults: int = 2
) -> dict:
    r = await api.post(
        api.h("/reservations/quote"),
        {
            "arrival": iso(arrival),
            "departure": iso(arrival, nights),
            "rooms": [{"room_type_id": s["rt"], "adults": adults, "rate_plan_id": plan}],
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


def prices(q: dict) -> list[str]:
    return [n["price"] for n in q["rooms"][0]]


async def rule(api: Api, **body) -> dict:
    r = await api.post(api.h("/pricing-rules"), {"name": {"en": body.pop("label", "Rule")}, **body})
    assert r.status_code == 201, r.text
    return r.json()


async def test_every_hotel_gets_a_default_plan_and_policies(admin: Api, setup):
    plans = (await admin.get(admin.h("/rate-plans"))).json()
    assert [(p["code"], p["is_default"]) for p in plans] == [("BAR", True)]
    assert set(plans[0]["name"]) == {"en", "fr", "zh-CN", "ru", "km"}
    codes = {p["code"] for p in (await admin.get(admin.h("/cancellation-policies"))).json()}
    assert codes == {"FLEX", "NONREF"}


async def test_seasons_and_weekend_rules_stack_by_priority(admin: Api, setup):
    await rule(
        admin,
        label="High season",
        kind="season",
        priority=10,
        date_from=iso(MON),
        date_to=iso(MON, 13),
        adjustment="percent",
        value="50",
    )
    await rule(
        admin, label="Weekend", kind="weekday", priority=20, weekdays=[4, 5], adjustment="amount", value="20"
    )
    q = await quote(admin, setup, MON - timedelta(days=1), 7)  # Sunday before the season → Saturday
    # Sun (no season) 100; Mon-Thu season 150; Fri, Sat season + weekend 170.
    assert prices(q) == ["100.00", "150.00", "150.00", "150.00", "150.00", "170.00", "170.00"]
    assert q["accommodation_total"] == "1040.00"


async def test_explicit_grid_price_beats_rules_but_not_discounts(admin: Api, setup):
    await rule(
        admin, kind="season", date_from=iso(MON), date_to=iso(MON, 30), adjustment="percent", value="50"
    )
    await rule(
        admin,
        label="Long stay",
        kind="long_stay",
        conditions={"min_nights": 3},
        adjustment="percent",
        value="-10",
    )
    r = await admin.post(
        admin.h("/rates/bulk"),
        {
            "rate_plan_ids": [setup["bar"]],
            "room_type_ids": [setup["rt"]],
            "start": iso(MON),
            "end": iso(MON),
            "price": {"mode": "set", "value": "80"},
        },
    )
    assert r.status_code == 200 and r.json()["cells_changed"] == 1
    q = await quote(admin, setup, MON, 3)
    # Night 1: explicit 80 → -10% = 72; nights 2-3: 100 +50% = 150 → -10% = 135.
    assert prices(q) == ["72.00", "135.00", "135.00"]
    # Two nights: the long-stay discount no longer applies.
    assert prices(await quote(admin, setup, MON, 2)) == ["80.00", "150.00"]


async def test_derived_plans(admin: Api, setup):
    nonref = await admin.post(
        admin.h("/rate-plans"),
        {
            "code": "NRF",
            "name": {"en": "Non-refundable"},
            "is_refundable": False,
            "parent_rate_plan_id": setup["bar"],
            "derive_mode": "percent",
            "derive_value": "-10",
        },
    )
    assert nonref.status_code == 201, nonref.text
    bb = (
        await admin.post(
            admin.h("/rate-plans"),
            {
                "code": "BB",
                "name": {"en": "Bed & breakfast"},
                "meal_plan": "breakfast",
                "parent_rate_plan_id": setup["bar"],
                "derive_mode": "amount_per_person",
                "derive_value": "12",
            },
        )
    ).json()
    assert prices(await quote(admin, setup, MON, 1, nonref.json()["id"])) == ["90.00"]
    assert prices(await quote(admin, setup, MON, 1, bb["id"])) == ["124.00"]
    # Third adult: +20 supplement and +12 breakfast.
    assert prices(await quote(admin, setup, MON, 1, bb["id"], adults=3)) == ["156.00"]
    # An explicit BAR price flows into the derived plans.
    await admin.post(
        admin.h("/rates/bulk"),
        {
            "rate_plan_ids": [setup["bar"]],
            "room_type_ids": [setup["rt"]],
            "start": iso(MON),
            "end": iso(MON),
            "price": {"mode": "set", "value": "200"},
        },
    )
    assert prices(await quote(admin, setup, MON, 1, nonref.json()["id"])) == ["180.00"]


async def test_booking_window_discounts(admin: Api, setup):
    today = hotel_today()
    await rule(
        admin,
        label="Last minute",
        kind="last_minute",
        conditions={"max_days_before": 2},
        adjustment="percent",
        value="-20",
    )
    await rule(
        admin,
        label="Early bird",
        kind="early_bird",
        conditions={"min_days_before": 45},
        adjustment="percent",
        value="-10",
    )
    assert prices(await quote(admin, setup, today + timedelta(days=1), 1)) == ["80.00"]
    assert prices(await quote(admin, setup, today + timedelta(days=10), 1)) == ["100.00"]
    assert prices(await quote(admin, setup, MON, 1)) == ["90.00"]


async def test_occupancy_based_pricing(admin: Api, setup):
    await rule(
        admin,
        label="High demand",
        kind="occupancy",
        conditions={"min_occupancy": 60},
        adjustment="percent",
        value="25",
    )
    assert prices(await quote(admin, setup, MON, 1)) == ["100.00"]
    for room in setup["rooms"][:2]:  # 2 of 3 rooms sold = 66 %
        r = await admin.post(
            admin.h("/reservations"),
            {
                "arrival": iso(MON),
                "departure": iso(MON, 1),
                "guest": {"first_name": "A", "last_name": "B"},
                "rooms": [{"room_type_id": setup["rt"], "room_id": room, "adults": 2}],
            },
        )
        assert r.status_code == 201, r.text
    assert prices(await quote(admin, setup, MON, 1)) == ["125.00"]


async def test_restrictions_block_bookings_unless_overridden(admin: Api, setup, user_factory):
    bulk = {"rate_plan_ids": [setup["bar"]], "room_type_ids": [setup["rt"]]}
    await admin.post(
        admin.h("/rates/bulk"), {**bulk, "start": iso(MON), "end": iso(MON), "restrictions": {"min_stay": 3}}
    )
    await admin.post(
        admin.h("/rates/bulk"),
        {**bulk, "start": iso(MON, 10), "end": iso(MON, 10), "restrictions": {"closed": True}},
    )
    await admin.post(
        admin.h("/rates/bulk"),
        {**bulk, "start": iso(MON, 20), "end": iso(MON, 20), "restrictions": {"closed_to_arrival": True}},
    )
    await admin.post(
        admin.h("/rates/bulk"),
        {**bulk, "start": iso(MON, 32), "end": iso(MON, 32), "restrictions": {"closed_to_departure": True}},
    )

    def booking(a: int, b: int, **extra) -> dict:
        return {
            "arrival": iso(MON, a),
            "departure": iso(MON, b),
            "guest": {"first_name": "R", "last_name": "S"},
            "rooms": [{"room_type_id": setup["rt"], "adults": 2}],
            **extra,
        }

    for (a, b), code in {
        (0, 2): "MIN_STAY_NOT_MET",
        (9, 11): "STOP_SELL",
        (20, 21): "CLOSED_TO_ARRIVAL",
        (30, 32): "CLOSED_TO_DEPARTURE",
    }.items():
        r = await admin.post(admin.h("/reservations"), booking(a, b))
        assert r.status_code == 409 and error_code(r) == code, (a, b, r.text)
    assert (await admin.post(admin.h("/reservations"), booking(0, 3))).status_code == 201
    q = await quote(admin, setup, MON, 2)
    assert q["stays"][0]["issues"] == [{"code": "MIN_STAY_NOT_MET", "min_stay": 3}]

    clerk = await user_factory("receptionist")
    r = await clerk.post(clerk.h("/reservations"), booking(9, 11, override_restrictions=True))
    assert r.status_code == 403
    r = await admin.post(admin.h("/reservations"), booking(9, 11, override_restrictions=True))
    assert r.status_code == 201, r.text
    events = (await admin.get(admin.h(f"/reservations/{r.json()['id']}/events"))).json()
    assert events[0]["details"]["restrictions_overridden"] == ["STOP_SELL"]


async def test_derived_plans_inherit_restrictions(admin: Api, setup):
    nrf = (
        await admin.post(
            admin.h("/rate-plans"),
            {
                "code": "NRF",
                "name": {"en": "NRF"},
                "parent_rate_plan_id": setup["bar"],
                "derive_mode": "percent",
                "derive_value": "-10",
            },
        )
    ).json()
    await admin.post(
        admin.h("/rates/bulk"),
        {
            "rate_plan_ids": [setup["bar"]],
            "room_type_ids": [setup["rt"]],
            "start": iso(MON),
            "end": iso(MON),
            "restrictions": {"closed": True},
        },
    )
    assert (await quote(admin, setup, MON, 1, nrf["id"]))["stays"][0]["issues"][0]["code"] == "STOP_SELL"
    grid = (
        await admin.get(
            admin.h("/rates/grid"), params={"rate_plan_id": nrf["id"], "start": iso(MON), "end": iso(MON, 1)}
        )
    ).json()
    assert grid["cells"][0]["closed"] is True and grid["cells"][0]["restrictions_inherited"] is True
    assert grid["cells"][0]["price"] == "90.00" and grid["cells"][0]["source"] == "derived"


async def test_bulk_edit_percent_weekdays_and_clear(admin: Api, setup):
    base = {
        "rate_plan_ids": [setup["bar"]],
        "room_type_ids": [setup["rt"]],
        "start": iso(MON),
        "end": iso(MON, 6),
    }
    r = await admin.post(
        admin.h("/rates/bulk"), {**base, "weekdays": [5, 6], "price": {"mode": "percent", "value": "10"}}
    )
    assert r.json()["cells_changed"] == 2
    grid = (
        await admin.get(
            admin.h("/rates/grid"),
            params={"rate_plan_id": setup["bar"], "start": iso(MON), "end": iso(MON, 7)},
        )
    ).json()
    assert [(c["price"], c["explicit"]) for c in grid["cells"]] == [("100.00", False)] * 5 + [
        ("110.00", True)
    ] * 2
    assert grid["cells"][0]["available"] == 3
    r = await admin.post(admin.h("/rates/bulk"), {**base, "price": {"mode": "clear"}})
    assert r.json()["cells_changed"] == 2
    grid = (
        await admin.get(
            admin.h("/rates/grid"),
            params={"rate_plan_id": setup["bar"], "start": iso(MON), "end": iso(MON, 7)},
        )
    ).json()
    assert all(not c["explicit"] and c["price"] == "100.00" for c in grid["cells"])
    r = await admin.post(admin.h("/rates/bulk"), {**base})
    assert r.status_code == 422  # nothing to change
    logs = (await admin.get(admin.h("/audit-logs"), params={"entity_type": "rate"})).json()["items"]
    assert logs and logs[0]["action"] == "rate.bulk_update"


async def test_offers_list_every_bookable_plan(admin: Api, setup):
    nrf = (
        await admin.post(
            admin.h("/rate-plans"),
            {
                "code": "NRF",
                "name": {"en": "NRF"},
                "parent_rate_plan_id": setup["bar"],
                "derive_mode": "percent",
                "derive_value": "-10",
                "min_advance_days": 7,
            },
        )
    ).json()
    offers = (
        await admin.get(admin.h("/rates/offers"), params={"arrival": iso(MON), "departure": iso(MON, 2)})
    ).json()
    by_plan = {o["rate_plan_id"]: o for o in offers}
    assert by_plan[setup["bar"]]["total"] == "200.00" and by_plan[nrf["id"]]["total"] == "180.00"
    assert all(o["bookable"] and o["available"] == 3 for o in offers)
    soon = hotel_today() + timedelta(days=2)
    offers = (
        await admin.get(
            admin.h("/rates/offers"),
            params={
                "arrival": soon.isoformat(),
                "departure": (soon + timedelta(days=1)).isoformat(),
                "adults": 4,
            },
        )
    ).json()
    nrf_offer = next(o for o in offers if o["rate_plan_id"] == nrf["id"])
    codes = {i["code"] for i in nrf_offer["issues"]}
    assert codes == {"RATE_PLAN_BOOKING_WINDOW", "OCCUPANCY_EXCEEDED"} and not nrf_offer["bookable"]


async def test_changing_a_stays_rate_plan_reprices_it(admin: Api, setup):
    bb = (
        await admin.post(
            admin.h("/rate-plans"),
            {
                "code": "BB",
                "name": {"en": "B&B"},
                "meal_plan": "breakfast",
                "parent_rate_plan_id": setup["bar"],
                "derive_mode": "amount_per_person",
                "derive_value": "10",
            },
        )
    ).json()
    res = (
        await admin.post(
            admin.h("/reservations"),
            {
                "arrival": iso(MON),
                "departure": iso(MON, 2),
                "guest": {"first_name": "C", "last_name": "D"},
                "rooms": [{"room_type_id": setup["rt"], "adults": 2}],
            },
        )
    ).json()
    assert res["rooms"][0]["rate_plan_id"] == setup["bar"] and res["accommodation_total"] == "200.00"
    rr = res["rooms"][0]["id"]
    r = await admin.post(
        admin.h(f"/reservations/{res['id']}/rooms/{rr}/rate-plan"),
        {"version": res["version"], "rate_plan_id": bb["id"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["accommodation_total"] == "240.00" and r.json()["rooms"][0]["rate_plan_id"] == bb["id"]
    # Extending the stay prices the new night with the stay's own plan.
    r2 = await admin.post(
        admin.h(f"/reservations/{res['id']}/rooms/{rr}/dates"),
        {"version": r.json()["version"], "arrival": iso(MON), "departure": iso(MON, 3)},
    )
    assert [n["price"] for n in r2.json()["rooms"][0]["nights"]] == ["120.00", "120.00", "120.00"]
    events = (await admin.get(admin.h(f"/reservations/{res['id']}/events"))).json()
    assert any(e["action"] == "rate_plan_changed" and e["details"]["new"] == "BB" for e in events)


async def test_rate_changes_never_reprice_existing_bookings(admin: Api, setup):
    res = (
        await admin.post(
            admin.h("/reservations"),
            {
                "arrival": iso(MON),
                "departure": iso(MON, 2),
                "guest": {"first_name": "E", "last_name": "F"},
                "rooms": [{"room_type_id": setup["rt"], "adults": 2}],
            },
        )
    ).json()
    await admin.post(
        admin.h("/rates/bulk"),
        {
            "rate_plan_ids": [setup["bar"]],
            "room_type_ids": [setup["rt"]],
            "start": iso(MON),
            "end": iso(MON, 5),
            "price": {"mode": "set", "value": "300"},
        },
    )
    await rule(
        admin, kind="season", date_from=iso(MON), date_to=iso(MON, 5), adjustment="percent", value="100"
    )
    same = (await admin.get(admin.h(f"/reservations/{res['id']}"))).json()
    assert same["accommodation_total"] == "200.00"


async def test_plan_and_rule_validation(admin: Api, setup):
    a = (
        await admin.post(
            admin.h("/rate-plans"),
            {
                "code": "A",
                "name": {"en": "A"},
                "parent_rate_plan_id": setup["bar"],
                "derive_mode": "amount",
                "derive_value": "5",
            },
        )
    ).json()
    r = await admin.patch(
        admin.h(f"/rate-plans/{setup['bar']}"),
        {"version": 1, "parent_rate_plan_id": a["id"], "derive_mode": "amount", "derive_value": "1"},
    )
    assert r.status_code == 422 and error_code(r) == "RATE_PLAN_CYCLE"
    r = await admin.post(
        admin.h("/rate-plans"), {"code": "B", "name": {"en": "B"}, "parent_rate_plan_id": a["id"]}
    )
    assert r.status_code == 422 and error_code(r) == "DERIVATION_REQUIRED"
    assert error_code(await admin.delete(admin.h(f"/rate-plans/{setup['bar']}"))) == "DEFAULT_PLAN_REQUIRED"
    # Making another plan the default moves the flag.
    r = await admin.patch(admin.h(f"/rate-plans/{a['id']}"), {"version": a["version"], "is_default": True})
    assert r.status_code == 200
    defaults = [p["code"] for p in (await admin.get(admin.h("/rate-plans"))).json() if p["is_default"]]
    assert defaults == ["A"]
    # A parent plan cannot be deleted while other plans derive from it...
    r = await admin.delete(admin.h(f"/rate-plans/{setup['bar']}"))
    assert r.status_code == 409 and error_code(r) == "RATE_PLAN_HAS_CHILDREN"
    # ...and a plan used by a booking cannot be deleted at all.
    c = (await admin.post(admin.h("/rate-plans"), {"code": "C", "name": {"en": "C"}})).json()
    booked = await admin.post(
        admin.h("/reservations"),
        {
            "arrival": iso(MON),
            "departure": iso(MON, 1),
            "guest": {"first_name": "G", "last_name": "H"},
            "rooms": [{"room_type_id": setup["rt"], "rate_plan_id": c["id"]}],
        },
    )
    assert booked.status_code == 201, booked.text
    r = await admin.delete(admin.h(f"/rate-plans/{c['id']}"))
    assert r.status_code == 409 and error_code(r) == "RATE_PLAN_IN_USE"
    r = await admin.post(
        admin.h("/pricing-rules"),
        {"name": {"en": "x"}, "kind": "long_stay", "adjustment": "percent", "value": "-5"},
    )
    assert r.status_code == 422 and error_code(r) == "RULE_CONDITION_REQUIRED"
    r = await admin.post(
        admin.h("/pricing-rules"),
        {"name": {"en": "x"}, "kind": "season", "adjustment": "percent", "value": "5"},
    )
    assert error_code(r) == "SEASON_DATES_REQUIRED"


async def test_pricing_permissions(user_factory, setup):
    clerk = await user_factory("receptionist")
    assert (await clerk.get(clerk.h("/rate-plans"))).status_code == 200
    r = await clerk.post(
        clerk.h("/rates/bulk"),
        {
            "rate_plan_ids": [setup["bar"]],
            "room_type_ids": [setup["rt"]],
            "start": iso(MON),
            "end": iso(MON),
            "price": {"mode": "set", "value": "1"},
        },
    )
    assert r.status_code == 403
