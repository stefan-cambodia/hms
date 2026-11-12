"""Vehicle rental: pricing, no double booking (database constraint, also under
concurrency), safety rules, pick-up and return, late fees, payments and room
charge, contract PDF."""

from __future__ import annotations

import asyncio
import io
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pypdf import PdfReader
from sqlalchemy import text

from app.core.db import sessionmaker
from tests.conftest import Api, error_code
from tests.test_reservations import _parallel_clients


def now() -> datetime:
    return datetime.now(UTC).replace(second=0, microsecond=0)


def iso(dt: datetime) -> str:
    return dt.isoformat()


def hotel_day(offset: int = 0) -> str:
    return (datetime.now(ZoneInfo("Asia/Phnom_Penh")).date() + timedelta(days=offset)).isoformat()


@pytest.fixture
async def fleet(admin: Api) -> dict:
    """VAT 10%. Scooter S1: 10/day, 2/hour, deposit 50. Car C1: 40/day, driver
    20/day. Bicycle B1: 3/day."""
    await admin.post(
        admin.h("/tax-rates"), {"code": "VAT", "name": {"en": "VAT"}, "kind": "percent", "rate": "10"}
    )
    out = {}
    for body in (
        {
            "code": "S1",
            "kind": "scooter",
            "make": "Honda",
            "model": "Scoopy",
            "plate": "1A-1234",
            "daily_rate": "10",
            "hourly_rate": "2",
            "deposit_amount": "50",
            "insurance_expiry": hotel_day(200),
        },
        {
            "code": "C1",
            "kind": "car",
            "make": "Toyota",
            "model": "Camry",
            "daily_rate": "40",
            "driver_daily_rate": "20",
            "seats": 4,
        },
        {"code": "B1", "kind": "bicycle", "daily_rate": "3"},
    ):
        r = await admin.post(admin.h("/vehicles"), body)
        assert r.status_code == 201, r.text
        out[body["code"]] = r.json()
    return out


def rental(vehicle: dict, start: datetime, end: datetime, **extra) -> dict:
    return {
        "vehicle_id": vehicle["id"],
        "start_at": iso(start),
        "end_at": iso(end),
        "guest": {"first_name": "Sam", "last_name": "Rider"},
        **extra,
    }


async def book(api: Api, body: dict) -> dict:
    r = await api.post(api.h("/vehicle-rentals"), body)
    assert r.status_code == 201, r.text
    return r.json()


async def test_pricing(admin: Api, fleet):
    start = now() + timedelta(days=3)

    async def q(code: str, hours: float, driver: bool = False) -> dict:
        r = await admin.get(
            admin.h("/vehicle-rentals/quote"),
            params={
                "vehicle_id": fleet[code]["id"],
                "start": iso(start),
                "end": iso(start + timedelta(hours=hours)),
                "with_driver": str(driver).lower(),
            },
        )
        assert r.status_code == 200, r.text
        return r.json()

    assert (await q("S1", 0.5))["base_amount"] == "2.00"  # one started hour
    assert (await q("S1", 26))["base_amount"] == "14.00"  # 1 day + 2 h × 2
    assert (await q("S1", 30))["base_amount"] == "20.00"  # 6 h capped at a day
    car = await q("C1", 25, driver=True)  # no hourly rate: 2 started days
    assert (car["base_amount"], car["driver_amount"], car["total"]) == ("80.00", "40.00", "132.00")
    r = await admin.get(
        admin.h("/vehicle-rentals/quote"),
        params={
            "vehicle_id": fleet["B1"]["id"],
            "start": iso(start),
            "end": iso(start + timedelta(hours=2)),
            "with_driver": "true",
        },
    )
    assert r.status_code == 422 and error_code(r) == "NO_DRIVER_SERVICE"


async def test_a_vehicle_is_never_double_booked(admin: Api, fleet):
    s1 = fleet["S1"]
    start = now() + timedelta(days=3)
    first = await book(admin, rental(s1, start, start + timedelta(days=2)))
    assert first["number"] == "RNT-000001" and first["total"] == "22.00"
    r = await admin.post(
        admin.h("/vehicle-rentals"), rental(s1, start + timedelta(days=1), start + timedelta(days=3))
    )
    assert r.status_code == 409 and error_code(r) == "VEHICLE_UNAVAILABLE"
    # Back to back is fine.
    await book(admin, rental(s1, start + timedelta(days=2), start + timedelta(days=3)))
    # Ten devices race for the same scooter on the same day: exactly one wins.
    day = start + timedelta(days=10)
    apis = await _parallel_clients(admin, 6)
    try:
        results = await asyncio.gather(
            *(api.post(api.h("/vehicle-rentals"), rental(s1, day, day + timedelta(hours=5))) for api in apis)
        )
    finally:
        for api in apis:
            await api.client.aclose()
    codes = sorted(r.status_code for r in results)
    assert codes == [201, 409, 409, 409, 409, 409]
    # The database itself refuses an overlap, whatever the code path.
    async with sessionmaker()() as db:
        with pytest.raises(Exception, match="ex_vehicle_rentals_no_overlap"):
            await db.execute(
                text(
                    "UPDATE vehicle_rentals SET start_at = start_at - interval '1 day' "
                    "WHERE number = 'RNT-000002'"
                )
            )
        await db.rollback()
    # Cancelling frees the vehicle.
    r = await admin.post(
        admin.h(f"/vehicle-rentals/{first['id']}/cancel"),
        {"version": first["version"], "reason": "Changed plans"},
    )
    assert r.status_code == 200 and r.json()["status"] == "cancelled" and r.json()["total"] == "0.00"
    await book(admin, rental(s1, start + timedelta(hours=1), start + timedelta(hours=5)))
    listed = (
        await admin.get(
            admin.h("/vehicles"), params={"start": iso(day), "end": iso(day + timedelta(hours=1))}
        )
    ).json()
    flags = {v["code"]: (v["available"], v["unavailable_reason"]) for v in listed}
    assert flags == {"S1": (False, "booked"), "C1": (True, None), "B1": (True, None)}


async def test_safety_rules(admin: Api, fleet):
    s1, c1 = fleet["S1"], fleet["C1"]
    start = now() + timedelta(days=3)
    r = await admin.patch(
        admin.h(f"/vehicles/{s1['id']}"), {"version": s1["version"], "insurance_expiry": hotel_day(-1)}
    )
    s1 = r.json()
    assert s1["document_warning"] == "insurance_expiry_expired"
    r = await admin.post(admin.h("/vehicle-rentals"), rental(s1, start, start + timedelta(days=1)))
    assert r.status_code == 409 and error_code(r) == "INSURANCE_EXPIRED"
    r = await admin.patch(
        admin.h(f"/vehicles/{c1['id']}"), {"version": c1["version"], "status": "maintenance"}
    )
    r = await admin.post(admin.h("/vehicle-rentals"), rental(r.json(), start, start + timedelta(days=1)))
    assert r.status_code == 409 and error_code(r) == "VEHICLE_NOT_AVAILABLE"


async def test_pickup_return_and_late_fee(admin: Api, fleet, user_factory):
    s1 = fleet["S1"]
    receptionist = await user_factory("receptionist")
    # Booked for 2 hours that ended an hour ago (the renter is late).
    late = await book(receptionist, rental(s1, now() - timedelta(hours=3), now() - timedelta(hours=1)))
    r = await receptionist.post(
        receptionist.h(f"/vehicle-rentals/{late['id']}/pickup"),
        {"version": late["version"], "odometer_out": 1500},
    )
    assert r.status_code == 422 and error_code(r) == "LICENCE_REQUIRED"
    r = await receptionist.post(
        receptionist.h(f"/vehicle-rentals/{late['id']}/pickup"),
        {
            "version": late["version"],
            "odometer_out": 1500,
            "fuel_out": 8,
            "licence_number": "KH-B-778899",
            "licence_country": "KH",
            "deposit_kind": "cash",
            "condition_out": "Scratch on left mirror",
        },
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "out" and out["licence_last4"] == "8899" and out["overdue"] is True
    assert out["deposit_amount"] == "50.00" and out["deposit_currency"] == "USD"
    async with sessionmaker()() as db:
        stored = (
            await db.execute(
                text("SELECT licence_number FROM vehicle_rentals WHERE id = :i"), {"i": late["id"]}
            )
        ).scalar()
    assert stored and b"778899" not in bytes(stored)  # encrypted at rest

    # The next renter cannot take the scooter while it is still out.
    nxt = await book(receptionist, rental(s1, now(), now() + timedelta(hours=2)))
    r = await receptionist.post(
        receptionist.h(f"/vehicle-rentals/{nxt['id']}/pickup"),
        {"version": nxt["version"], "odometer_out": 1500, "licence_number": "X1234"},
    )
    assert r.status_code == 409 and error_code(r) == "VEHICLE_NOT_RETURNED"

    r = await receptionist.post(
        receptionist.h(f"/vehicle-rentals/{late['id']}/return"),
        {"version": out["version"], "odometer_in": 1400},
    )
    assert r.status_code == 422 and error_code(r) == "ODOMETER_BELOW_RECORDED"
    r = await receptionist.post(
        receptionist.h(f"/vehicle-rentals/{late['id']}/return"),
        {"version": out["version"], "odometer_in": 1542, "fuel_in": 6, "waive_late_fee": True},
    )
    assert r.status_code == 403  # waiving the late fee needs vehicles.manage
    r = await receptionist.post(
        receptionist.h(f"/vehicle-rentals/{late['id']}/return"),
        {"version": out["version"], "odometer_in": 1542, "fuel_in": 6, "fuel_charge": "1.50"},
    )
    assert r.status_code == 200, r.text
    back = r.json()
    # 3 h actual vs 2 h planned at 2.00/h: late fee 2.00; + fuel 1.50; VAT 10%.
    assert (back["base_amount"], back["late_fee"], back["fuel_charge"], back["total"]) == (
        "4.00",
        "2.00",
        "1.50",
        "8.25",
    )
    assert back["deposit_returned_at"] is not None and back["status"] == "returned"
    vehicles = {v["code"]: v for v in (await admin.get(admin.h("/vehicles"))).json()}
    assert vehicles["S1"]["odometer"] == 1542
    # Now the next renter can go.
    r = await receptionist.post(
        receptionist.h(f"/vehicle-rentals/{nxt['id']}/pickup"),
        {"version": nxt["version"], "odometer_out": 1542, "licence_number": "X1234"},
    )
    assert r.status_code == 200

    r = await receptionist.post(
        receptionist.h("/vehicles"), {"code": "S2", "kind": "scooter", "daily_rate": "9"}
    )
    assert r.status_code == 403  # fleet management needs vehicles.manage


async def test_payments_cash_change_and_room_charge(admin: Api, fleet):
    # An in-house guest rents a bicycle (no licence needed).
    rt = (
        await admin.post(
            admin.h("/room-types"),
            {
                "code": "STD",
                "name": {"en": "Standard"},
                "base_occupancy": 2,
                "max_occupancy": 2,
                "max_adults": 2,
                "max_children": 0,
                "base_price": "40.00",
            },
        )
    ).json()
    room = (
        await admin.post(admin.h("/rooms/bulk"), {"room_type_id": rt["id"], "start": 101, "end": 101})
    ).json()[0]
    res = (
        await admin.post(
            admin.h("/reservations"),
            {
                "arrival": hotel_day(0),
                "departure": hotel_day(2),
                "guest": {"first_name": "Ana", "last_name": "Silva"},
                "rooms": [{"room_type_id": rt["id"], "room_id": room["id"], "adults": 2}],
                "override_restrictions": True,
            },
        )
    ).json()
    res = (
        await admin.post(admin.h(f"/reservations/{res['id']}/check-in"), {"version": res["version"]})
    ).json()
    rr_id = res["rooms"][0]["id"]
    bike = await book(
        admin,
        {
            "vehicle_id": fleet["B1"]["id"],
            "start_at": iso(now()),
            "end_at": iso(now() + timedelta(hours=8)),
            "reservation_room_id": rr_id,
        },
    )
    assert bike["guest_name"] == "Ana Silva" and bike["room_number"] == "101" and bike["in_house"] is True
    bike = (
        await admin.post(
            admin.h(f"/vehicle-rentals/{bike['id']}/pickup"), {"version": bike["version"], "odometer_out": 0}
        )
    ).json()
    r = await admin.post(admin.h(f"/vehicle-rentals/{bike['id']}/payments"), {"method": "room_charge"})
    assert r.status_code == 409 and error_code(r) == "ROOM_CHARGE_AFTER_RETURN"
    bike = (
        await admin.post(
            admin.h(f"/vehicle-rentals/{bike['id']}/return"), {"version": bike["version"], "odometer_in": 0}
        )
    ).json()
    assert bike["total"] == "3.30"
    r = await admin.post(admin.h(f"/vehicle-rentals/{bike['id']}/payments"), {"method": "room_charge"})
    assert r.status_code == 201, r.text
    assert r.json()["balance"] == "0.00" and r.json()["payments"][0]["room_number"] == "101"
    folio = (await admin.get(admin.h(f"/reservations/{res['id']}/folio"))).json()
    [charge] = [c for c in folio["charges"] if c["kind"] == "outlet"]
    assert charge["name"]["en"] == "Vehicle rental" and charge["description"] == bike["number"]
    assert (charge["amount"], charge["tax_amount"]) == ("3.00", "0.30")
    r = await admin.post(
        admin.h(f"/vehicle-rentals/{bike['id']}/payments/{r.json()['payments'][0]['id']}/void"),
        {"reason": "Paid cash"},
    )
    assert r.status_code == 200 and r.json()["balance"] == "3.30"
    folio = (await admin.get(admin.h(f"/reservations/{res['id']}/folio"))).json()
    assert [c["is_void"] for c in folio["charges"] if c["kind"] == "outlet"] == [True]

    r = await admin.post(
        admin.h(f"/vehicle-rentals/{bike['id']}/payments"), {"method": "cash", "amount": "5.00"}
    )
    assert r.status_code == 201 and r.json()["change_due"] == "1.70" and r.json()["balance"] == "0.00"

    pdf = await admin.get(admin.h(f"/vehicle-rentals/{bike['id']}/contract.pdf"), params={"language": "km"})
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    reader = PdfReader(io.BytesIO(pdf.content))
    assert bike["number"] in reader.pages[0].extract_text()


async def test_no_show_rules(admin: Api, fleet):
    start = now() + timedelta(days=1)
    r = await book(admin, rental(fleet["C1"], start, start + timedelta(days=1)))
    resp = await admin.post(admin.h(f"/vehicle-rentals/{r['id']}/no-show"), {"version": r["version"]})
    assert resp.status_code == 409 and error_code(resp) == "NO_SHOW_BEFORE_START"
    r2 = await book(admin, rental(fleet["B1"], now() - timedelta(hours=2), now() + timedelta(hours=2)))
    resp = await admin.post(admin.h(f"/vehicle-rentals/{r2['id']}/no-show"), {"version": r2["version"]})
    assert resp.status_code == 200 and resp.json()["status"] == "no_show"
    assert date.fromisoformat(hotel_day(0))  # sanity: fixture dates are hotel-local


async def test_in_house_guest_search_is_for_staff_who_settle(admin: Api, user_factory):
    receptionist = await user_factory("receptionist")  # rents vehicles, takes folio payments
    waiter = await user_factory("waiter")  # settles restaurant checks
    maid = await user_factory("housekeeping")
    assert (await receptionist.get(receptionist.h("/in-house-guests"))).status_code == 200
    assert (await waiter.get(waiter.h("/in-house-guests"))).status_code == 200
    assert (await maid.get(maid.h("/in-house-guests"))).status_code == 403


async def test_early_hand_over_and_immediate_return(admin: Api, fleet):
    b1 = fleet["B1"]
    r = await book(admin, rental(b1, now() + timedelta(hours=1), now() + timedelta(hours=25)))
    r = (
        await admin.post(
            admin.h(f"/vehicle-rentals/{r['id']}/pickup"), {"version": r["version"], "odometer_out": 0}
        )
    ).json()
    assert r["status"] == "out" and r["start_at"] <= r["picked_up_at"]
    back = await admin.post(
        admin.h(f"/vehicle-rentals/{r['id']}/return"), {"version": r["version"], "odometer_in": 0}
    )
    assert back.status_code == 200, back.text
    assert back.json()["late_fee"] == "0.00" and back.json()["base_amount"] == "3.00"
