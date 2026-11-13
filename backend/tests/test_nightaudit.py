"""End-of-day closure (night audit): rules for closing, the day's figures,
open items, and the freeze of closed days."""

from __future__ import annotations

import io

from pypdf import PdfReader
from sqlalchemy import text

from app.core.db import owner_sessionmaker
from tests.conftest import Api, error_code
from tests.test_reports import d, room_type
from tests.test_restaurant import add, in_house_guest, open_check, pay, resto  # noqa: F401 (fixture)


async def audit(api: Api, day: int | None = None) -> dict:
    r = await api.get(api.h("/night-audit"), params={"date": d(day)} if day is not None else None)
    assert r.status_code == 200, r.text
    return r.json()


async def close(api: Api, day: int, **body) -> dict:
    return await api.post(api.h(f"/night-audit/{d(day)}/close"), body)


async def book(admin: Api, rt: str, arrival: int, departure: int, room_id: str | None = None) -> dict:
    r = await admin.post(
        admin.h("/reservations"),
        {
            "arrival": d(arrival),
            "departure": d(departure),
            "guest": {"first_name": "Sok", "last_name": "Dara"},
            "rooms": [{"room_type_id": rt, "adults": 2, "room_id": room_id}],
            "override_restrictions": True,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_days_close_in_order_and_only_once_over(admin: Api):
    view = await audit(admin)
    assert view["date"] == d(-1) and view["can_close"] and view["last_closed"] is None
    today = await audit(admin, 0)
    assert (today["can_close"], today["blocker"]) == (False, "DAY_NOT_OVER")
    r = await close(admin, 0)
    assert r.status_code == 409 and error_code(r) == "DAY_NOT_OVER"

    # The first closure may be any past day; then days follow one another.
    assert (await close(admin, -3)).status_code == 200
    r = await close(admin, -1)
    assert r.status_code == 409 and error_code(r) == "PREVIOUS_DAY_OPEN"
    assert (await audit(admin))["date"] == d(-2)  # the screen proposes the next day to close
    assert (await close(admin, -2)).status_code == 200
    closed = await close(admin, -1, notes="Quiet night")
    assert closed.status_code == 200, closed.text
    body = closed.json()
    assert body["closure"]["closed_by_name"] == "Admin" and body["closure"]["notes"] == "Quiet night"
    r = await close(admin, -1)
    assert r.status_code == 409 and error_code(r) == "ALREADY_CLOSED"
    history = (await admin.get(admin.h("/night-audit/closures"))).json()
    assert [h["date"] for h in history] == [d(-1), d(-2), d(-3)]

    # Closures are append-only, also for the API's own database role.
    from app.core.db import sessionmaker

    async with sessionmaker()() as db:
        for sql in ("UPDATE day_closures SET notes = 'x'", "DELETE FROM day_closures"):
            try:
                await db.execute(text(sql))
                raise AssertionError(f"{sql} was allowed")
            except Exception as exc:  # noqa: BLE001
                assert "permission denied" in str(exc)
            await db.rollback()


async def test_open_items_must_be_accepted_and_are_recorded(admin: Api):
    rt = await room_type(admin, "A", 3, 101)
    rooms = {r["number"]: r["id"] for r in (await admin.get(admin.h("/rooms"))).json()}
    expected = await book(admin, rt, -1, 2, rooms["101"])  # due yesterday, not arrived
    await book(admin, rt, 0, 2)  # arriving today without a room ("tomorrow" for yesterday)
    view = await audit(admin, -1)
    items = view["open_items"]
    assert [s["code"] for s in items["not_arrived"]] == [expected["code"]]
    assert len(items["unassigned_tomorrow"]) == 1
    assert view["open_count"] == 2

    r = await close(admin, -1)
    assert r.status_code == 422 and error_code(r) == "OPEN_ITEMS"
    # The night auditor decides: here, a no-show for the guest who did not come.
    r = await admin.post(
        admin.h(f"/reservations/{expected['id']}/no-show"),
        {"version": expected["version"], "waive_fee": True},
    )
    assert r.status_code == 200, r.text
    view = await audit(admin, -1)
    assert view["open_items"]["not_arrived"] == [] and view["open_count"] == 1
    r = await close(admin, -1, accept_open_items=True)
    assert r.status_code == 200, r.text
    closed = r.json()
    assert closed["open_count"] == 1 and len(closed["open_items"]["unassigned_tomorrow"]) == 1
    assert closed["report"]["movements"]["no_shows"] == 1


async def test_day_figures_and_cash_up(admin: Api, resto):  # noqa: F811
    guest = await in_house_guest(admin)  # arrived yesterday, 2 nights
    res_id = guest["id"]
    for body in (
        {"method": "card", "amount": "100.00", "card_brand": "visa", "card_last4": "4242"},
        {"method": "cash", "amount": "50.00"},
        {"kind": "refund", "method": "cash", "amount": "20.00"},
    ):
        r = await admin.post(admin.h(f"/reservations/{res_id}/payments"), body)
        assert r.status_code == 201, r.text
    order = await add(admin, resto, await open_check(admin, resto), ("beer", 2))
    assert (await admin.post(admin.h(f"/restaurant/orders/{order['id']}/send"))).status_code == 200
    r = await pay(admin, order, method="cash", amount=order["total"])
    assert r.status_code == 201, r.text

    report = (await audit(admin, 0))["report"]
    assert report["rooms"]["sold"] == 1 and report["rooms"]["available"] == 1
    assert report["movements"]["arrivals"] == 1  # checked in today (by the helper)
    by_method = {p["method"]: p["amount_base"] for p in report["payments_by_method"]}
    cash = 50 - 20 + float(order["total"])
    assert float(by_method["card"]) == 100 and round(float(by_method["cash"]), 2) == round(cash, 2)
    assert round(float(report["payments_net"]), 2) == round(100 + cash, 2)
    sources = {(p["source"], p["kind"], p["method"]) for p in report["payments"]}
    assert ("restaurant", "payment", "cash") in sources and ("folio", "refund", "cash") in sources


async def test_closed_days_are_frozen(admin: Api):
    guest = await in_house_guest(admin)
    res_id = guest["id"]
    r = await admin.post(
        admin.h(f"/reservations/{res_id}/charges"),
        {"kind": "service", "description": "Minibar", "unit_price": "6.50", "service_date": d(-1)},
    )
    assert r.status_code == 201, r.text
    folio = (await admin.get(admin.h(f"/reservations/{res_id}/folio"))).json()
    charge = next(c for c in folio["charges"] if c["description"] == "Minibar")
    r = await admin.post(admin.h(f"/reservations/{res_id}/payments"), {"method": "cash", "amount": "10.00"})
    assert r.status_code == 201, r.text
    folio = (await admin.get(admin.h(f"/reservations/{res_id}/folio"))).json()
    payment = folio["payments"][0]
    # That payment was received yesterday (back-dated by the schema owner: the
    # API only records payments now; the append-only trigger is lifted for it).
    async with owner_sessionmaker()() as db:
        await db.execute(text("ALTER TABLE payments DISABLE TRIGGER trg_payments_immutable"))
        await db.execute(
            text("UPDATE payments SET received_at = received_at - interval '1 day' WHERE id = :id"),
            {"id": payment["id"]},
        )
        await db.execute(text("ALTER TABLE payments ENABLE TRIGGER trg_payments_immutable"))
        await db.commit()

    assert (await close(admin, -1, accept_open_items=True)).status_code == 200

    r = await admin.post(
        admin.h(f"/reservations/{res_id}/charges"),
        {"kind": "service", "description": "Late minibar", "unit_price": "3.00", "service_date": d(-1)},
    )
    assert r.status_code == 409 and error_code(r) == "DAY_CLOSED"
    r = await admin.post(
        admin.h(f"/reservations/{res_id}/charges/{charge['id']}/void"), {"reason": "Wrong room"}
    )
    assert r.status_code == 409 and error_code(r) == "DAY_CLOSED"
    r = await admin.post(admin.h(f"/reservations/{res_id}/payments/{payment['id']}/void"), {"reason": "Typo"})
    assert r.status_code == 409 and error_code(r) == "DAY_CLOSED"
    # Corrections go on the current day.
    r = await admin.post(
        admin.h(f"/reservations/{res_id}/charges"),
        {"kind": "adjustment", "description": "Minibar charged to the wrong room", "unit_price": "-6.50"},
    )
    assert r.status_code == 201, r.text
    r = await admin.post(
        admin.h(f"/reservations/{res_id}/payments"), {"kind": "refund", "method": "cash", "amount": "10.00"}
    )
    assert r.status_code == 201, r.text


async def test_permissions_and_pdf(admin: Api, user_factory):
    receptionist = await user_factory("receptionist")
    assert (await receptionist.get(receptionist.h("/night-audit"))).status_code == 200
    housekeeper = await user_factory("housekeeping")
    assert (await housekeeper.get(housekeeper.h("/night-audit"))).status_code == 403
    assert (await housekeeper.get(housekeeper.h("/night-audit/closures"))).status_code == 403

    r = await receptionist.post(receptionist.h(f"/night-audit/{d(-1)}/close"), {"accept_open_items": True})
    assert r.status_code == 200, r.text
    # Receptionists see the cash-up, not the revenue (financial reports).
    report = r.json()["report"]
    assert report["revenue"] is None and report["rooms"]["revenue"] is None
    assert report["payments_net"] is not None

    pdf = await admin.get(admin.h(f"/night-audit/{d(-1)}/report.pdf"), params={"language": "fr"})
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    text_ = "".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf.content)).pages)
    assert "Rapport de clôture de journée" in text_ and "Encaissements" in text_
    missing = await admin.get(admin.h(f"/night-audit/{d(-5)}/report.pdf"))
    assert missing.status_code == 404 and error_code(missing) == "DAY_NOT_CLOSED"
