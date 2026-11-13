"""Realistic activity for the documentation screenshots.

Run on a fresh database that holds only the demo hotel (`hms bootstrap` +
`hms seed-demo`), never on a hotel in service:

    backend/.venv/bin/python tools/screenshots/seed_activity.py \
        --base http://127.0.0.1:8000 --email admin@demo.local --password ... \
        --owner-dsn postgresql://hms:...@127.0.0.1:54329/hms_shots

Everything goes through the API, except what the API rightly refuses to do
in the past: guests who checked in on earlier days and stays that already
ended are back-dated with the schema owner's connection (`--owner-dsn`).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import random
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import asyncpg
import httpx

TZ = ZoneInfo("Asia/Phnom_Penh")
random.seed(20261113)

GUESTS = [
    ("Camille", "Durand", "FR", "fr"), ("Wei", "Zhang", "CN", "zh-CN"), ("James", "Wilson", "GB", "en"),
    ("Anna", "Petrova", "RU", "ru"), ("Minh", "Nguyen", "VN", "en"), ("Sarah", "Miller", "US", "en"),
    ("Yuki", "Tanaka", "JP", "en"), ("Lukas", "Becker", "DE", "en"), ("Somchai", "Wongsakul", "TH", "en"),
    ("Elena", "Rossi", "IT", "en"), ("Pierre", "Martin", "FR", "fr"), ("Li", "Na", "CN", "zh-CN"),
    ("Dmitri", "Ivanov", "RU", "ru"), ("Olivia", "Brown", "AU", "en"), ("Hiroshi", "Sato", "JP", "en"),
    ("Maria", "Garcia", "ES", "en"), ("Ji-woo", "Park", "KR", "en"), ("Noah", "Johnson", "CA", "en"),
    ("Chantrea", "Sok", "KH", "km"), ("Sophie", "Laurent", "BE", "fr"), ("Jie", "Chen", "SG", "zh-CN"),
    ("Ivan", "Smirnov", "RU", "ru"), ("Emma", "Taylor", "NZ", "en"), ("Thomas", "Müller", "DE", "en"),
    ("Aiko", "Yamamoto", "JP", "en"), ("Ravi", "Sharma", "IN", "en"), ("Lucas", "Silva", "BR", "en"),
    ("Ingrid", "Larsen", "NO", "en"), ("Vanna", "Meas", "KH", "km"), ("Julien", "Moreau", "FR", "fr"),
    ("Hui", "Lin", "TW", "zh-CN"), ("Olga", "Kuznetsova", "RU", "ru"), ("Ben", "Carter", "GB", "en"),
    ("Mia", "Schmidt", "AT", "en"), ("Kenji", "Watanabe", "JP", "en"),
]
FIRST = ["Alex", "Nora", "Daniel", "Chloé", "Bopha", "Hana", "Marco", "Lea", "Sam", "Yan", "Irina", "Tom", "Mei",
         "Paul", "Sreymom", "Kai", "Laura", "Arjun", "Eva", "Nikolai"]
LAST = ["Dubois", "Kowalski", "Hughes", "Chhay", "Ito", "Novak", "Lambert", "Wu", "Popov", "Evans", "Seng",
        "Fischer", "Ng", "Bernard", "Khiev", "Andersen"]

# (guest index, arrival offset, nights, room or category, adults, source, plan)
IN_HOUSE = [
    (0, -2, 4, "101", 2, "direct", "BB"), (1, -1, 4, "102", 2, "booking_com", "BAR"),
    (2, -3, 4, "104", 1, "agoda", "NRF"), (3, -1, 5, "106", 2, "booking_com", "BB"),
    (4, -4, 6, "108", 2, "phone", "BAR"), (5, -2, 7, "110", 2, "direct", "BB"),
    (6, -2, 5, "201", 2, "booking_com", "BB"), (7, -1, 3, "203", 2, "direct", "BAR"),
    (8, -5, 6, "205", 1, "agoda", "NRF"),
]
DEPARTING = [(9, -3, 3, "103", 2, "booking_com", "BB"), (10, -2, 2, "107", 1, "direct", "BAR"),
             (11, -4, 4, "202", 2, "agoda", "BB")]
ARRIVING = [(12, 0, 3, "105", 2, "booking_com", "BB"), (13, 0, 2, "109", 1, "direct", "BAR"),
            (14, 0, 4, "204", 2, "booking_com", "BB"), (15, 0, 2, "STD-DBL", 2, "agoda", "BAR"),
            (16, 0, 3, "DLX", 2, "phone", "BB")]
FUTURE = [
    (17, 1, 3, "103", 2, "direct", "BAR"), (18, 2, 2, "107", 2, "walk_in", "BAR"),
    (19, 1, 4, "202", 2, "booking_com", "BB"), (20, 2, 4, "104", 1, "agoda", "NRF"),
    (21, 1, 2, "111", 2, "booking_com", "BAR"), (22, 3, 4, "112", 2, "direct", "BB"),
    (23, 2, 3, "205", 2, "booking_com", "BB"), (24, 4, 4, "206", 2, "agoda", "BB"),
    (25, 3, 3, "108", 1, "phone", "BAR"), (26, 5, 4, "101", 2, "booking_com", "NRF"),
    (27, 6, 4, "102", 2, "direct", "BB"), (28, 5, 2, "111", 2, "website", "BAR"),
    (29, 8, 3, "STD-DBL", 2, "booking_com", "BAR"), (30, 9, 3, "DLX", 2, "agoda", "BB"),
    (31, 12, 3, "STD-DBL", 2, "email", "BB"), (32, 15, 3, "STD-DBL", 1, "booking_com", "BAR"),
]
CANCELLED = [(33, 6, 2, "STD-DBL", 2, "booking_com", "BAR")]
NO_SHOW = [(34, -1, 2, "STD-DBL", 1, "agoda", "BAR")]


class Api:
    def __init__(self, base: str) -> None:
        self.client = httpx.AsyncClient(base_url=base + "/api/v1", timeout=60)
        self.hotel = ""

    async def login(self, email: str, password: str) -> dict:
        r = await self.client.post("/auth/login", json={"email": email, "password": password})
        r.raise_for_status()
        me = r.json()
        self.client.headers["X-CSRF-Token"] = me["csrf_token"]
        self.hotel = me["hotels"][0]["id"]
        return me

    async def __call__(self, method: str, path: str, body: Any = None, **kw: Any) -> Any:
        url = path if path.startswith("/auth") else f"/hotels/{self.hotel}{path}"
        r = await self.client.request(method, url, json=body, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"{method} {path}: {r.status_code} {r.text[:300]}")
        return r.json() if r.content else None


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), TZ).astimezone(UTC)


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--base", required=True)
    p.add_argument("--email", required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--owner-dsn", required=True)
    args = p.parse_args()
    api = Api(args.base)
    me = await api.login(args.email, args.password)
    today = datetime.now(TZ).date()
    owner = await asyncpg.connect(args.owner_dsn)

    types = {t["code"]: t for t in await api("GET", "/room-types")}
    rooms = {r["number"]: r for r in await api("GET", "/rooms")}
    plans = {p["code"]: p for p in await api("GET", "/rate-plans")}

    async def book(spec: tuple, guest: tuple | None = None) -> dict:
        gi, offset, nights, where, adults, source, plan = spec
        first, last, country, lang = guest or GUESTS[gi]
        room = rooms.get(where)
        type_id = room["room_type_id"] if room else types[where]["id"]
        arrival = today + timedelta(days=offset)
        body = {
            "arrival": arrival.isoformat(),
            "departure": (arrival + timedelta(days=nights)).isoformat(),
            "guest": {
                "first_name": first,
                "last_name": last,
                "nationality": country,
                "country_code": country,
                "preferred_language": lang,
                "email": f"{first}.{last}@example.com".lower().replace("ü", "u").replace("é", "e"),
            },
            "rooms": [{"room_type_id": type_id, "room_id": room["id"] if room else None, "adults": adults,
                       "rate_plan_id": plans[plan]["id"]}],
            "source": source,
            "external_ref": f"{random.randint(1_000_000_000, 9_999_999_999)}" if source in ("booking_com", "agoda") else None,
        }
        key = hashlib.sha256(f"{first}|{last}|{offset}|{where}".encode()).hexdigest()[:40]
        return await api("POST", "/reservations", body, headers={"Idempotency-Key": key})

    # --- Staff --------------------------------------------------------------
    roles = {r["code"]: r["id"] for r in await api("GET", "/roles")}
    staff = {}
    for email, name, role in [
        ("lina@lotus.local", "Lina Heng", "receptionist"), ("bopha@lotus.local", "Bopha Keo", "manager"),
        ("sreypov@lotus.local", "Srey Pov Lim", "housekeeping"), ("vuthy@lotus.local", "Vuthy Ros", "maintenance"),
        ("rithy@lotus.local", "Rithy Som", "accountant"), ("malis@lotus.local", "Malis Ouk", "waiter"),
    ]:
        staff[role] = await api("POST", "/users", {"email": email, "full_name": name, "password": "Lotus-Staff-2026",
                                                    "role_ids": [roles[role]]})

    # --- History: stays that ended in the last five weeks (for the reports) --
    first_current: dict[str, date] = {}
    for spec in IN_HOUSE + DEPARTING + ARRIVING:
        if spec[3] in rooms:
            first_current[spec[3]] = today + timedelta(days=spec[1])
    past: list[dict] = []
    for number in sorted(rooms):
        end = first_current.get(number, today)
        while True:
            nights = random.choice((1, 2, 2, 3, 3, 4))
            end -= timedelta(days=random.choice((0, 0, 1, 2)))
            start = end - timedelta(days=nights)
            if start < today - timedelta(days=35):
                break
            guest = (random.choice(FIRST), random.choice(LAST), random.choice(["FR", "US", "GB", "CN", "KH", "DE", "JP", "AU", "RU"]), "en")
            spec = (0, (start - today).days, nights, number, random.choice((1, 2, 2)),
                    random.choice(("direct", "booking_com", "booking_com", "agoda", "phone", "walk_in")),
                    random.choice(("BAR", "BB", "NRF")))
            past.append(await book(spec, guest))
            end = start
    for res in past:  # settled at departure
        balance = (await api("GET", f"/reservations/{res['id']}/folio"))["totals"]["balance"]
        method = random.choice(("card", "card", "card", "cash", "bank_transfer"))
        body = {"kind": "payment", "method": method, "amount": balance}
        if method == "card":
            body |= {"card_brand": random.choice(("visa", "mastercard", "unionpay", "jcb")),
                     "card_last4": f"{random.randint(0, 9999):04d}"}
        await api("POST", f"/reservations/{res['id']}/payments", body)
    for res in past:
        await owner.execute(
            "UPDATE reservation_rooms SET checked_in_at = $2, checked_out_at = $3 WHERE reservation_id = $1",
            res["id"], at(date.fromisoformat(res["arrival"]), 14, random.randint(0, 59)),
            at(date.fromisoformat(res["departure"]), 11, random.randint(0, 30)),
        )
        await owner.execute("UPDATE reservations SET status = 'checked_out' WHERE id = $1", res["id"])

    # --- Current stays --------------------------------------------------------
    in_house = [await book(s) for s in IN_HOUSE]
    for res in in_house:
        r = await api("POST", f"/reservations/{res['id']}/check-in", {"version": res["version"]})
        await owner.execute("UPDATE reservation_rooms SET checked_in_at = $2 WHERE reservation_id = $1",
                            res["id"], at(date.fromisoformat(res["arrival"]), 14, random.randint(0, 59)))
        res.update(r)
    departing = [await book(s) for s in DEPARTING]
    for res in departing:  # checked in on an earlier day, leaving today
        await owner.execute("UPDATE reservation_rooms SET checked_in_at = $2 WHERE reservation_id = $1",
                            res["id"], at(date.fromisoformat(res["arrival"]), 15, random.randint(0, 59)))
        await owner.execute("UPDATE reservations SET status = 'checked_in' WHERE id = $1", res["id"])
    arriving = [await book(s) for s in ARRIVING]
    early = arriving[1]  # arrived early this morning
    await api("POST", f"/reservations/{early['id']}/check-in", {"version": early["version"]})
    for s in FUTURE:
        await book(s)
    for s in CANCELLED:
        res = await book(s)
        await api("POST", f"/reservations/{res['id']}/cancel", {"version": res["version"], "reason": "Change of travel plans"})
    for s in NO_SHOW:
        res = await book(s)
        await api("POST", f"/reservations/{res['id']}/no-show", {"version": res["version"], "waive_fee": False})

    # --- Folios: extras and payments -------------------------------------------
    extras = [("Minibar", "6.50"), ("Laundry", "8.00"), ("Airport transfer", "15.00"), ("Spa massage (60 min)", "28.00"),
              ("Dinner, Riverside Restaurant", "24.00")]
    for res in in_house + departing:
        for desc, price in random.sample(extras, random.randint(1, 3)):
            await api("POST", f"/reservations/{res['id']}/charges",
                      {"kind": "service", "description": desc, "unit_price": price})
        if res["source"] in ("booking_com", "agoda", "direct"):
            amount = (await api("GET", f"/reservations/{res['id']}/folio"))["totals"]["balance"]
            method = random.choice(("card", "card", "cash"))
            body: dict[str, Any] = {"kind": "payment", "method": method,
                                    "amount": str(round(float(amount) * random.choice((0.5, 1.0)), 2))}
            if method == "card":
                body |= {"card_brand": random.choice(("visa", "mastercard", "unionpay")),
                         "card_last4": f"{random.randint(0, 9999):04d}"}
            if float(body["amount"]) > 0:
                await api("POST", f"/reservations/{res['id']}/payments", body)

    # --- Housekeeping and maintenance -----------------------------------------
    for number in ("103", "107", "202"):  # guests leaving today: rooms to clean after departure
        await api("POST", f"/rooms/{rooms[number]['id']}/housekeeping-status", {"status": "dirty"})
    for number in ("111", "112", "206"):
        await api("POST", f"/rooms/{rooms[number]['id']}/housekeeping-status", {"status": "inspected"})
    await api("POST", "/housekeeping/prepare")
    tasks = await api("GET", "/housekeeping/tasks")
    if tasks:
        await api("POST", "/housekeeping/tasks/assign",
                  {"task_ids": [t["id"] for t in tasks], "user_id": staff["housekeeping"]["id"]})
        for t in tasks[:2]:
            await api("POST", f"/housekeeping/tasks/{t['id']}/start", {})
        await api("POST", f"/housekeeping/tasks/{tasks[0]['id']}/complete", {})
    facilities = await api("GET", "/facilities")
    pool = next((f for f in facilities if f.get("code") == "POOL"), None)
    for body in [
        {"room_id": rooms["206"]["id"], "category": "air_conditioning", "priority": "high",
         "title": "Air conditioning not cooling", "description": "Guest reported warm air since last night.",
         "assigned_to": staff["maintenance"]["id"]},
        {"room_id": rooms["108"]["id"], "category": "plumbing", "priority": "normal",
         "title": "Dripping bathroom tap", "assigned_to": staff["maintenance"]["id"]},
        {"facility_id": pool["id"] if pool else None, "location": None if pool else "Pool", "category": "other",
         "priority": "low", "title": "Pool pump noisy in the morning"},
    ]:
        await api("POST", "/maintenance-requests", {k: v for k, v in body.items() if v is not None})

    # --- Restaurant -------------------------------------------------------------
    outlet = await api("POST", "/restaurant/outlets", {
        "code": "MAIN",
        "name": {"en": "Riverside Restaurant", "fr": "Restaurant du Fleuve", "km": "ភោជនីយដ្ឋានមាត់ទន្លេ",
                 "zh-CN": "河畔餐厅", "ru": "Ресторан у реки"},
        "service_charge_percent": "10",
    })
    food = await api("POST", "/restaurant/categories", {"outlet_id": outlet["id"], "name": {"en": "Khmer dishes", "fr": "Plats khmers"}})
    drinks = await api("POST", "/restaurant/categories", {"outlet_id": outlet["id"], "name": {"en": "Drinks", "fr": "Boissons"}})
    menu = {}
    for cat, en, fr, price, station in [
        (food, "Fish amok", "Amok de poisson", "8.00", "kitchen"), (food, "Beef lok lak", "Lok lak de bœuf", "7.50", "kitchen"),
        (food, "Nom banh chok", "Nom banh chok", "4.50", "kitchen"), (food, "Fried rice with shrimp", "Riz sauté aux crevettes", "5.50", "kitchen"),
        (food, "Mango sticky rice", "Riz gluant à la mangue", "3.50", "kitchen"), (drinks, "Angkor beer", "Bière Angkor", "2.50", "bar"),
        (drinks, "Fresh coconut", "Noix de coco fraîche", "2.00", "bar"), (drinks, "Iced coffee with milk", "Café glacé au lait", "2.00", "bar"),
        (drinks, "Mineral water", "Eau minérale", "1.00", "none"),
    ]:
        menu[en] = await api("POST", "/restaurant/menu-items",
                             {"category_id": cat["id"], "name": {"en": en, "fr": fr}, "price": price, "station": station})
    tables = {}
    for n in range(1, 9):
        tables[n] = await api("POST", "/restaurant/tables", {"outlet_id": outlet["id"], "label": f"T{n}", "seats": 4 if n < 7 else 6})
    for table, covers, items in [
        (2, 2, [("Fish amok", 1), ("Beef lok lak", 1), ("Angkor beer", 2)]),
        (5, 4, [("Nom banh chok", 2), ("Fried rice with shrimp", 2), ("Fresh coconut", 4)]),
        (7, 3, [("Mango sticky rice", 3), ("Iced coffee with milk", 3)]),
    ]:
        order = await api("POST", "/restaurant/orders", {"outlet_id": outlet["id"], "table_id": tables[table]["id"], "covers": covers})
        await api("POST", f"/restaurant/orders/{order['id']}/lines",
                  {"items": [{"menu_item_id": menu[name]["id"], "quantity": q} for name, q in items]})
        if table != 7:
            await api("POST", f"/restaurant/orders/{order['id']}/send")
    yuki = in_house[6]
    rs = await api("POST", "/restaurant/orders", {"outlet_id": outlet["id"], "order_type": "room_service",
                                                   "reservation_room_id": yuki["rooms"][0]["id"], "covers": 2})
    await api("POST", f"/restaurant/orders/{rs['id']}/lines",
              {"items": [{"menu_item_id": menu["Fish amok"]["id"], "quantity": 2}, {"menu_item_id": menu["Mineral water"]["id"], "quantity": 2}]})
    await api("POST", f"/restaurant/orders/{rs['id']}/send")

    # --- Vehicles -----------------------------------------------------------------
    fleet = {}
    for v in [
        {"code": "SC-01", "kind": "scooter", "make": "Honda", "model": "Scoopy", "plate": "1A-2041", "daily_rate": "10", "hourly_rate": "2", "deposit_amount": "50", "odometer": 12040},
        {"code": "SC-02", "kind": "scooter", "make": "Honda", "model": "Click", "plate": "1A-2042", "daily_rate": "10", "hourly_rate": "2", "deposit_amount": "50", "odometer": 8015},
        {"code": "SC-03", "kind": "scooter", "make": "Yamaha", "model": "NMAX", "plate": "1A-2043", "daily_rate": "14", "hourly_rate": "3", "deposit_amount": "80", "odometer": 5120},
        {"code": "CAR-01", "kind": "car", "make": "Toyota", "model": "Camry", "plate": "2B-7788", "daily_rate": "45", "driver_daily_rate": "25", "seats": 4, "deposit_amount": "200", "transmission": "automatic"},
        {"code": "TT-01", "kind": "tuk_tuk", "make": "Bajaj", "model": "RE", "plate": "1C-0310", "daily_rate": "25", "seats": 4, "deposit_amount": "0"},
        {"code": "BK-01", "kind": "bicycle", "make": "Giant", "model": "Escape", "daily_rate": "3"},
    ]:
        fleet[v["code"]] = await api("POST", "/vehicles", v)
    james = in_house[2]
    rental = await api("POST", "/vehicle-rentals", {"vehicle_id": fleet["SC-01"]["id"], "start_at": at(today, 9).isoformat(),
                                                     "end_at": at(today + timedelta(days=1), 9).isoformat(),
                                                     "guest_id": james["booker"]["id"] if "booker" in james else None,
                                                     "reservation_room_id": james["rooms"][0]["id"]})
    await api("POST", f"/vehicle-rentals/{rental['id']}/pickup", {
        "version": rental["version"], "licence_number": "WILSO805123JA9", "licence_country": "GB",
        "licence_expiry": (today + timedelta(days=900)).isoformat(), "odometer_out": 12040, "fuel_out": 8,
        "deposit_kind": "passport"})
    sarah = in_house[5]
    await api("POST", "/vehicle-rentals", {"vehicle_id": fleet["CAR-01"]["id"], "with_driver": True,
                                            "start_at": at(today + timedelta(days=1), 8).isoformat(),
                                            "end_at": at(today + timedelta(days=1), 18).isoformat(),
                                            "reservation_room_id": sarah["rooms"][0]["id"],
                                            "notes": "Angkor Wat day trip, pick-up at the lobby"})

    for code, guest, start, days in (("SC-02", in_house[3], 1, 2), ("TT-01", in_house[0], 2, 1), ("SC-03", in_house[6], 3, 2)):
        await api("POST", "/vehicle-rentals", {"vehicle_id": fleet[code]["id"],
                                                "start_at": at(today + timedelta(days=start), 9).isoformat(),
                                                "end_at": at(today + timedelta(days=start + days), 9).isoformat(),
                                                "reservation_room_id": guest["rooms"][0]["id"]})

    # --- Channel manager: a SiteMinder connection in the test environment --------
    # Sending and receiving are left off: nothing is sent to SiteMinder.
    conn = await api("POST", "/channel-connections", {
        "provider": "siteminder", "name": "SiteMinder", "environment": "test", "account_code": "LOTUSPMS",
        "username": "lotus-riverside", "password": "Demo-Only-Password", "hotel_code": "LOTUS123",
        "push_ari": False, "pull_reservations": False})
    await api("PUT", f"/channel-connections/{conn['id']}/mappings", {
        "rooms": [{"room_type_id": types["STD-DBL"]["id"], "external_code": "DBL"},
                  {"room_type_id": types["DLX"]["id"], "external_code": "DLXRIV"}],
        "rates": [{"room_type_id": types[t]["id"], "rate_plan_id": plans[p]["id"], "external_code": code}
                  for t in ("STD-DBL", "DLX") for p, code in (("BAR", "FLEX"), ("NRF", "NONREF"), ("BB", "BB"))],
    })
    # --- Make the history look like a hotel in service for a while -------------
    # Rooms and categories set up a year ago; each booking made before its
    # arrival (1 to 40 days); history entries at the time they happened.
    # Set up just before the history starts (no comparison with a year in
    # which the hotel did not use the system).
    await owner.execute("UPDATE room_types SET created_at = now() - interval '36 days'")
    await owner.execute("UPDATE rooms SET created_at = now() - interval '36 days'")
    await owner.execute(
        """
        UPDATE reservations SET created_at = least(
          now() - random() * interval '2 days',
          (arrival - (1 + floor(random() * 40))::int)::timestamp AT TIME ZONE 'Asia/Phnom_Penh'
            + random() * interval '10 hours' + interval '8 hours')
        WHERE source <> 'walk_in'
        """
    )
    await owner.execute(
        "UPDATE reservations SET created_at = (arrival::timestamp + interval '15 hours') AT TIME ZONE 'Asia/Phnom_Penh' "
        "WHERE source = 'walk_in' AND arrival <= current_date"
    )
    await owner.execute(
        "UPDATE reservation_events e SET at = r.created_at FROM reservations r "
        "WHERE e.reservation_id = r.id AND e.action = 'created'"
    )
    await owner.execute(
        "UPDATE reservation_events e SET at = rr.checked_in_at FROM reservation_rooms rr "
        "WHERE e.reservation_id = rr.reservation_id AND e.action = 'checked_in' AND rr.checked_in_at IS NOT NULL"
    )
    await owner.execute(
        "UPDATE guests g SET created_at = first.at FROM "
        "(SELECT booker_guest_id AS id, min(created_at) AS at FROM reservations GROUP BY 1) first "
        "WHERE g.id = first.id"
    )
    # Payments of past stays were received on their departure day. Payments
    # are append-only (a trigger refuses any change): this demo-data tool
    # lifts the trigger for that one update, as the schema owner.
    async with owner.transaction():
        await owner.execute("ALTER TABLE payments DISABLE TRIGGER trg_payments_immutable")
        await owner.execute(
            "UPDATE payments p SET received_at = t.at, created_at = t.at FROM ("
            "  SELECT r.id, (r.departure::timestamp + interval '10 hours' + random() * interval '90 minutes')"
            "    AT TIME ZONE 'Asia/Phnom_Penh' AS at FROM reservations r WHERE r.status = 'checked_out') t "
            "WHERE p.reservation_id = t.id"
        )
        await owner.execute("ALTER TABLE payments ENABLE TRIGGER trg_payments_immutable")
    # Restaurant checks opened a little while ago.
    await owner.execute(
        "UPDATE restaurant_orders SET created_at = now() - (8 + random() * 40) * interval '1 minute' "
        "WHERE closed_at IS NULL"
    )
    await owner.execute(
        "UPDATE restaurant_order_lines l SET created_at = o.created_at, "
        "sent_at = CASE WHEN l.sent_at IS NULL THEN NULL ELSE o.created_at + interval '3 minutes' END "
        "FROM restaurant_orders o WHERE l.order_id = o.id"
    )
    await owner.close()
    await api.client.aclose()
    print(f"history {len(past)} stays, in house {len(in_house) + len(departing) + 1}, arrivals {len(ARRIVING)}, "
          f"future {len(FUTURE)}; signed in as {me['user']['full_name']}")


if __name__ == "__main__":
    asyncio.run(main())
