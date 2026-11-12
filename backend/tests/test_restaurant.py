"""Restaurant & bar: menu, tables, checks, kitchen, payments, room charge,
breakfast list, sales report, bills in 5 languages."""

from __future__ import annotations

import io
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pypdf import PdfReader

from tests.conftest import Api, error_code


def today() -> date:
    return datetime.now(ZoneInfo("Asia/Phnom_Penh")).date()


def d(offset: int) -> str:
    return (today() + timedelta(days=offset)).isoformat()


@pytest.fixture
async def resto(admin: Api) -> dict:
    """VAT 10% on everything; a restaurant with 10% service charge; Amok 8.00
    (kitchen), Beer 2.50 (bar), Water 1.00 (no station); tables T1, T2."""
    await admin.post(
        admin.h("/tax-rates"), {"code": "VAT", "name": {"en": "VAT"}, "kind": "percent", "rate": "10"}
    )
    outlet = (
        await admin.post(
            admin.h("/restaurant/outlets"),
            {
                "code": "MAIN",
                "name": {"en": "Riverside Restaurant", "km": "ភោជនីយដ្ឋាន"},
                "service_charge_percent": "10",
            },
        )
    ).json()
    food = (
        await admin.post(
            admin.h("/restaurant/categories"), {"outlet_id": outlet["id"], "name": {"en": "Food"}}
        )
    ).json()
    drinks = (
        await admin.post(
            admin.h("/restaurant/categories"), {"outlet_id": outlet["id"], "name": {"en": "Drinks"}}
        )
    ).json()

    async def item(category: dict, name: str, price: str, station: str) -> dict:
        r = await admin.post(
            admin.h("/restaurant/menu-items"),
            {"category_id": category["id"], "name": {"en": name}, "price": price, "station": station},
        )
        assert r.status_code == 201, r.text
        return r.json()

    items = {
        "amok": await item(food, "Fish amok", "8.00", "kitchen"),
        "beer": await item(drinks, "Beer", "2.50", "bar"),
        "water": await item(drinks, "Water", "1.00", "none"),
    }
    tables = {}
    for label in ("T1", "T2"):
        tables[label] = (
            await admin.post(
                admin.h("/restaurant/tables"), {"outlet_id": outlet["id"], "label": label, "seats": 4}
            )
        ).json()
    return {"outlet": outlet, "items": items, "tables": tables, "food": food}


async def open_check(api: Api, s: dict, table: str = "T1", covers: int = 2, **extra) -> dict:
    r = await api.post(
        api.h("/restaurant/orders"),
        {"outlet_id": s["outlet"]["id"], "table_id": s["tables"][table]["id"], "covers": covers, **extra},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def add(api: Api, s: dict, order: dict, *lines: tuple[str, int]) -> dict:
    r = await api.post(
        api.h(f"/restaurant/orders/{order['id']}/lines"),
        {"items": [{"menu_item_id": s["items"][k]["id"], "quantity": q} for k, q in lines]},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def pay(api: Api, order: dict, **body):
    return await api.post(api.h(f"/restaurant/orders/{order['id']}/payments"), body)


async def in_house_guest(admin: Api, meal_plan: str = "room_only") -> dict:
    """A guest who arrived yesterday (stays 2 nights), checked in."""
    rt = (
        await admin.post(
            admin.h("/room-types"),
            {
                "code": f"R{meal_plan[:3].upper()}",
                "name": {"en": "Room"},
                "base_occupancy": 2,
                "max_occupancy": 2,
                "max_adults": 2,
                "max_children": 0,
                "base_price": "40.00",
            },
        )
    ).json()
    start = 200 if meal_plan == "room_only" else 300
    room = (
        await admin.post(admin.h("/rooms/bulk"), {"room_type_id": rt["id"], "start": start, "end": start})
    ).json()[0]
    stay = {"room_type_id": rt["id"], "room_id": room["id"], "adults": 2}
    if meal_plan != "room_only":
        plans = (await admin.get(admin.h("/rate-plans"))).json()
        bar = next(p for p in plans if p["is_default"])
        plan = (
            await admin.post(
                admin.h("/rate-plans"),
                {
                    "code": "BB",
                    "name": {"en": "Bed & breakfast"},
                    "meal_plan": meal_plan,
                    "parent_rate_plan_id": bar["id"],
                    "derive_mode": "amount_per_person",
                    "derive_value": "5",
                },
            )
        ).json()
        stay["rate_plan_id"] = plan["id"]
    res = (
        await admin.post(
            admin.h("/reservations"),
            {
                "arrival": d(-1),
                "departure": d(1),
                "guest": {"first_name": "Bopha", "last_name": "Lim"},
                "rooms": [stay],
                "override_restrictions": True,
            },
        )
    ).json()
    r = await admin.post(admin.h(f"/reservations/{res['id']}/check-in"), {"version": res["version"]})
    assert r.status_code == 200, r.text
    return {**r.json(), "room_number": room["number"]}


async def test_check_totals_service_charge_vat_and_discount(admin: Api, resto, user_factory):
    order = await open_check(admin, resto)
    assert order["number"] == "CHK-000001" and order["status"] == "open"
    order = await add(admin, resto, order, ("amok", 2), ("beer", 2))
    # 16.00 + 5.00 = 21.00; service 10% = 2.10; VAT 10% of 23.10 = 2.31.
    assert (order["subtotal"], order["service_charge"], order["tax_total"], order["total"]) == (
        "21.00",
        "2.10",
        "2.31",
        "25.41",
    )
    waiter = await user_factory("waiter")
    r = await waiter.post(
        waiter.h(f"/restaurant/orders/{order['id']}/discount"),
        {"kind": "percent", "value": "10", "reason": "Regular"},
    )
    assert r.status_code == 403
    r = await admin.post(
        admin.h(f"/restaurant/orders/{order['id']}/discount"),
        {"kind": "percent", "value": "10", "reason": "Regular"},
    )
    body = r.json()
    # 21.00 − 2.10 = 18.90; service 1.89; VAT 2.08 (of 20.79); total 22.87.
    assert (body["discount_total"], body["service_charge"], body["tax_total"], body["total"]) == (
        "2.10",
        "1.89",
        "2.08",
        "22.87",
    )
    r = await admin.post(
        admin.h(f"/restaurant/orders/{order['id']}/discount"),
        {"kind": "amount", "value": "50", "reason": "x"},
    )
    assert r.status_code == 422 and error_code(r) == "DISCOUNT_TOO_LARGE"
    r = await admin.post(admin.h(f"/restaurant/orders/{order['id']}/discount"), {"kind": None})
    assert r.json()["total"] == "25.41"


async def test_tables_menu_and_permissions(admin: Api, resto, user_factory):
    waiter = await user_factory("waiter")
    kitchen = await user_factory("kitchen")
    r = await waiter.post(waiter.h("/restaurant/outlets"), {"code": "BAR", "name": {"en": "Bar"}})
    assert r.status_code == 403
    r = await admin.post(admin.h("/restaurant/outlets"), {"code": "MAIN", "name": {"en": "Again"}})
    assert r.status_code == 409 and error_code(r) == "OUTLET_CODE_EXISTS"

    first = await open_check(waiter, resto)
    r = await waiter.post(
        waiter.h("/restaurant/orders"),
        {"outlet_id": resto["outlet"]["id"], "table_id": resto["tables"]["T1"]["id"], "covers": 2},
    )
    assert r.status_code == 409 and error_code(r) == "TABLE_OCCUPIED"
    r = await waiter.patch(
        waiter.h(f"/restaurant/orders/{first['id']}"),
        {"version": first["version"], "table_id": resto["tables"]["T2"]["id"]},
    )
    assert r.status_code == 200 and r.json()["table_label"] == "T2"
    await open_check(waiter, resto, "T1")  # T1 is free again
    floor = (
        await waiter.get(waiter.h("/restaurant/floor"), params={"outlet_id": resto["outlet"]["id"]})
    ).json()
    assert {t["label"]: bool(t["order"]) for t in floor} == {"T1": True, "T2": True}

    # Sold out: the kitchen marks it, nobody can order it.
    amok = resto["items"]["amok"]
    r = await waiter.post(
        waiter.h(f"/restaurant/menu-items/{amok['id']}/availability"), {"is_available": False}
    )
    assert r.status_code == 403
    r = await kitchen.post(
        kitchen.h(f"/restaurant/menu-items/{amok['id']}/availability"), {"is_available": False}
    )
    assert r.status_code == 200 and r.json()["is_available"] is False
    r = await waiter.post(
        waiter.h(f"/restaurant/orders/{first['id']}/lines"),
        {"items": [{"menu_item_id": amok["id"], "quantity": 1}]},
    )
    assert r.status_code == 409 and error_code(r) == "ITEM_UNAVAILABLE"
    # A category in use cannot be deleted.
    r = await admin.delete(admin.h(f"/restaurant/categories/{resto['food']['id']}"))
    assert r.status_code == 409 and error_code(r) == "CATEGORY_IN_USE"


async def test_kitchen_flow_and_voids(admin: Api, resto, user_factory):
    waiter = await user_factory("waiter")
    kitchen = await user_factory("kitchen")
    order = await open_check(waiter, resto)
    order = await add(waiter, resto, order, ("amok", 1), ("beer", 1), ("water", 2))
    r = await waiter.post(waiter.h(f"/restaurant/orders/{order['id']}/send"))
    assert r.status_code == 200
    status = {ln["name"]["en"]: ln["status"] for ln in r.json()["lines"]}
    assert status == {"Fish amok": "sent", "Beer": "sent", "Water": "served"}
    assert (
        error_code(await waiter.post(waiter.h(f"/restaurant/orders/{order['id']}/send"))) == "NOTHING_TO_SEND"
    )

    tickets = (await kitchen.get(kitchen.h("/restaurant/kitchen"), params={"station": "kitchen"})).json()
    assert [[ln["name"]["en"] for ln in t["lines"]] for t in tickets] == [["Fish amok"]]
    assert tickets[0]["table_label"] == "T1"
    amok_line = tickets[0]["lines"][0]
    url = kitchen.h(f"/restaurant/orders/{order['id']}/lines/{amok_line['id']}/status")
    r = await waiter.post(
        waiter.h(f"/restaurant/orders/{order['id']}/lines/{amok_line['id']}/status"), {"status": "ready"}
    )
    assert r.status_code == 403  # only the kitchen marks food ready
    assert (await kitchen.post(url, {"status": "preparing"})).status_code == 200
    r = await kitchen.post(url, {"status": "ready"})
    assert r.status_code == 200 and r.json()["lines_ready"] == 1
    r = await waiter.post(waiter.h(f"/restaurant/orders/{order['id']}/served"))
    assert r.status_code == 200 and r.json()["lines_ready"] == 0
    r = await kitchen.post(url, {"status": "preparing"})
    assert r.status_code == 409 and error_code(r) == "INVALID_LINE_TRANSITION"

    current = (await waiter.get(waiter.h(f"/restaurant/orders/{order['id']}"))).json()
    beer = next(ln for ln in current["lines"] if ln["name"]["en"] == "Beer")
    r = await waiter.delete(waiter.h(f"/restaurant/orders/{order['id']}/lines/{beer['id']}"))
    assert r.status_code == 409 and error_code(r) == "LINE_ALREADY_SENT"
    r = await waiter.post(
        waiter.h(f"/restaurant/orders/{order['id']}/lines/{beer['id']}/void"), {"reason": "Spilled"}
    )
    assert r.status_code == 403  # voiding needs restaurant.void
    r = await admin.post(
        admin.h(f"/restaurant/orders/{order['id']}/lines/{beer['id']}/void"), {"reason": "Spilled"}
    )
    assert r.status_code == 200
    assert r.json()["subtotal"] == "10.00"  # 8.00 amok + 2 × 1.00 water

    # A new, unsent line can simply be removed or changed.
    body = await add(waiter, resto, order, ("beer", 1))
    new = next(ln for ln in body["lines"] if ln["status"] == "new")
    r = await waiter.patch(
        waiter.h(f"/restaurant/orders/{order['id']}/lines/{new['id']}"), {"quantity": 3, "notes": "Cold"}
    )
    assert r.status_code == 200 and r.json()["subtotal"] == "17.50"
    r = await waiter.delete(waiter.h(f"/restaurant/orders/{order['id']}/lines/{new['id']}"))
    assert r.status_code == 200 and r.json()["subtotal"] == "10.00"


async def test_payments_change_currency_and_closing(admin: Api, resto, user_factory):
    await admin.post(admin.h("/currencies"), {"code": "KHR", "units_per_base": "4000"})
    waiter = await user_factory("waiter")
    order = await open_check(waiter, resto)
    order = await add(waiter, resto, order, ("amok", 2), ("beer", 2))  # total 25.41
    r = await pay(waiter, order, method="cash", amount="30")
    assert r.status_code == 409 and error_code(r) == "UNSENT_ITEMS"
    await waiter.post(waiter.h(f"/restaurant/orders/{order['id']}/send"))
    r = await pay(waiter, order, method="card", amount="30.00", card_brand="visa", card_last4="1234")
    assert r.status_code == 409 and error_code(r) == "PAYMENT_EXCEEDS_BALANCE"
    r = await pay(waiter, order, method="cash", amount="40000", currency="KHR", exchange_rate="4000")
    assert r.status_code == 201, r.text
    assert r.json()["paid_total"] == "10.00" and r.json()["status"] == "open"
    r = await pay(waiter, order, method="cash", amount="20.00")
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "closed" and body["paid_total"] == "25.41" and body["change_due"] == "4.59"
    cash = body["payments"][-1]
    assert (cash["amount"], cash["tendered"]) == ("15.41", "20.00")
    r = await pay(waiter, order, method="cash", amount="1")
    assert r.status_code == 409 and error_code(r) == "ORDER_CLOSED"
    # Voiding a payment (manager) reopens the check.
    r = await admin.post(
        admin.h(f"/restaurant/orders/{order['id']}/payments/{cash['id']}/void"), {"reason": "Wrong check"}
    )
    assert r.status_code == 200 and r.json()["status"] == "open" and r.json()["balance"] == "15.41"


async def test_room_charge_posts_to_the_folio(admin: Api, resto):
    guest = await in_house_guest(admin)
    before = guest["grand_total"]
    order = await open_check(admin, resto)
    order = await add(admin, resto, order, ("amok", 2), ("beer", 2))
    await admin.post(admin.h(f"/restaurant/orders/{order['id']}/send"))
    rr_id = guest["rooms"][0]["id"]
    found = (await admin.get(admin.h("/restaurant/in-house"), params={"q": guest["room_number"]})).json()
    assert [g["reservation_room_id"] for g in found] == [rr_id]
    r = await pay(admin, order, method="room_charge", reservation_room_id=rr_id)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "closed" and body["payments"][0]["room_number"] == guest["room_number"]

    folio = (await admin.get(admin.h(f"/reservations/{guest['id']}/folio"))).json()
    [charge] = [c for c in folio["charges"] if c["kind"] == "outlet"]
    assert charge["name"]["en"] == "Riverside Restaurant" and charge["description"] == body["number"]
    assert charge["amount"] == "23.10" and charge["tax_amount"] == "2.31"
    res = (await admin.get(admin.h(f"/reservations/{guest['id']}"))).json()
    assert float(res["grand_total"]) == pytest.approx(float(before) + 25.41)
    # The folio cannot void it on its own: it is voided from the check.
    r = await admin.post(admin.h(f"/reservations/{guest['id']}/charges/{charge['id']}/void"), {"reason": "x"})
    assert r.status_code == 409 and error_code(r) == "VOID_FROM_OUTLET"
    r = await admin.post(
        admin.h(f"/restaurant/orders/{order['id']}/payments/{body['payments'][0]['id']}/void"),
        {"reason": "Guest paid cash"},
    )
    assert r.status_code == 200 and r.json()["status"] == "open"
    res = (await admin.get(admin.h(f"/reservations/{guest['id']}"))).json()
    assert res["grand_total"] == before

    # Only the whole check can go to the room, and only for a guest in house.
    await pay(admin, order, method="cash", amount="5.00")
    r = await pay(admin, order, method="room_charge", reservation_room_id=rr_id)
    assert r.status_code == 409 and error_code(r) == "ROOM_CHARGE_FULL_ONLY"
    other = await open_check(admin, resto, "T2")
    other = await add(admin, resto, other, ("water", 1))
    await admin.post(admin.h(f"/restaurant/orders/{other['id']}/send"))
    res = (await admin.get(admin.h(f"/reservations/{guest['id']}"))).json()
    await admin.post(
        admin.h(f"/reservations/{guest['id']}/payments"), {"method": "cash", "amount": res["balance"]}
    )
    res = (await admin.get(admin.h(f"/reservations/{guest['id']}"))).json()
    r = await admin.post(
        admin.h(f"/reservations/{guest['id']}/check-out"),
        {
            "version": res["version"],
            "shorten_stay": True,
            "allow_open_balance": True,
        },  # night released: credit
    )
    assert r.status_code == 200, r.text
    r = await pay(admin, other, method="room_charge", reservation_room_id=rr_id)
    assert r.status_code == 409 and error_code(r) == "GUEST_NOT_IN_HOUSE"


async def test_cancelling_a_check(admin: Api, resto, user_factory):
    waiter = await user_factory("waiter")
    order = await open_check(waiter, resto)
    await add(waiter, resto, order, ("amok", 1))
    await waiter.post(waiter.h(f"/restaurant/orders/{order['id']}/send"))
    r = await waiter.post(waiter.h(f"/restaurant/orders/{order['id']}/cancel"), {"reason": "Guests left"})
    assert r.status_code == 403  # food was already sent to the kitchen
    r = await admin.post(admin.h(f"/restaurant/orders/{order['id']}/cancel"), {"reason": "Guests left"})
    assert r.status_code == 200 and r.json()["status"] == "cancelled" and r.json()["total"] == "0.00"
    other = await open_check(waiter, resto)  # the table is free again
    await add(waiter, resto, other, ("water", 1))
    r = await waiter.post(waiter.h(f"/restaurant/orders/{other['id']}/cancel"), {"reason": "Mistake"})
    assert r.status_code == 200  # nothing was sent: no supervisor needed


async def test_breakfast_list(admin: Api, resto):
    bb = await in_house_guest(admin, "breakfast")
    await in_house_guest(admin)  # room only: not on the list
    rows = (await admin.get(admin.h("/restaurant/breakfast"))).json()
    assert [(r["room_number"], r["meal_plan"], r["served_covers"]) for r in rows] == [
        (bb["room_number"], "breakfast", None)
    ]
    rr_id = bb["rooms"][0]["id"]
    r = await admin.post(admin.h("/restaurant/breakfast"), {"reservation_room_id": rr_id, "covers": 3})
    assert r.status_code == 422 and error_code(r) == "TOO_MANY_COVERS"
    r = await admin.post(admin.h("/restaurant/breakfast"), {"reservation_room_id": rr_id, "covers": 2})
    assert r.status_code == 204
    rows = (await admin.get(admin.h("/restaurant/breakfast"))).json()
    assert rows[0]["served_covers"] == 2
    r = await admin.delete(admin.h(f"/restaurant/breakfast/{rr_id}"))
    assert r.status_code == 204
    # Tomorrow is the departure morning: breakfast is still included (night of today).
    rows = (await admin.get(admin.h("/restaurant/breakfast"), params={"day": d(1)})).json()
    assert len(rows) == 1
    rows = (await admin.get(admin.h("/restaurant/breakfast"), params={"day": d(2)})).json()
    assert rows == []


async def test_sales_report_and_bill_pdf(admin: Api, resto, user_factory):
    waiter = await user_factory("waiter")
    for table, lines in (("T1", [("amok", 2), ("beer", 2)]), ("T2", [("water", 3)])):
        order = await open_check(waiter, resto, table)
        order = await add(waiter, resto, order, *lines)
        await waiter.post(waiter.h(f"/restaurant/orders/{order['id']}/send"))
        await pay(waiter, order, method="card", amount=order["total"], card_brand="visa", card_last4="4242")
    r = await waiter.get(waiter.h("/restaurant/sales"), params={"start": d(0), "end": d(0)})
    assert r.status_code == 403
    report = (await admin.get(admin.h("/restaurant/sales"), params={"start": d(0), "end": d(0)})).json()
    assert report["orders"] == 2 and report["covers"] == 4
    assert report["subtotal"] == "24.00" and report["total"] == "29.04"
    assert [(c["name"]["en"], c["quantity"]) for c in report["by_category"]] == [("Food", 2), ("Drinks", 5)]
    assert report["top_items"][0]["name"]["en"] == "Water"
    assert [(m["method"], m["count"]) for m in report["by_method"]] == [("card", 2)]

    orders = (await admin.get(admin.h("/restaurant/orders"), params={"status": "closed"})).json()
    r = await admin.get(admin.h(f"/restaurant/orders/{orders[0]['id']}/bill.pdf"), params={"language": "km"})
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    reader = PdfReader(io.BytesIO(r.content))
    fonts = {
        str(f.get_object()["/BaseFont"]) for f in (reader.pages[0]["/Resources"].get("/Font") or {}).values()
    }
    assert any("Khmer" in f for f in fonts)
    assert orders[0]["number"] in reader.pages[0].extract_text()


async def test_tapping_an_item_again_adds_to_the_unsent_line(admin: Api, resto):
    order = await open_check(admin, resto)
    await add(admin, resto, order, ("amok", 1))
    body = await add(admin, resto, order, ("amok", 1))
    assert [(ln["name"]["en"], ln["quantity"]) for ln in body["lines"]] == [("Fish amok", 2)]
    await admin.post(admin.h(f"/restaurant/orders/{order['id']}/send"))
    body = await add(admin, resto, order, ("amok", 1))  # after sending: a new line
    assert sorted((ln["quantity"], ln["status"]) for ln in body["lines"]) == [(1, "new"), (2, "sent")]
