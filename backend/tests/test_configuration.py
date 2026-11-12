"""Phase 3 — hotel configuration."""

from __future__ import annotations

from tests.conftest import Api, error_code


async def test_hotel_profile_update_and_optimistic_locking(admin: Api):
    hotel = (await admin.get(admin.h(""))).json()
    r = await admin.patch(
        admin.h(""),
        {
            "version": hotel["version"],
            "name": "Seaside Resort",
            "description": {"en": "By the sea", "km": "នៅមាត់សមុទ្រ", "zh-CN": "海边", "fr": " "},
            "country_code": "KH",
            "timezone": "Asia/Phnom_Penh",
            "currency_code": "KHR",
            "check_in_time": "15:00",
            "website": "https://seaside.example",
            "social_links": {"facebook": "https://facebook.com/seaside"},
            "policies": {"cancellation": {"en": "Free until 48h", "ru": "Бесплатно до 48 ч"}},
            "billing_info": {"invoice_prefix": "INV-"},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["version"] == hotel["version"] + 1
    assert body["description"] == {"en": "By the sea", "km": "នៅមាត់សមុទ្រ", "zh-CN": "海边"}
    assert body["check_in_time"] == "15:00:00"
    assert body["policies"]["cancellation"]["ru"] == "Бесплатно до 48 ч"

    # A second editor holding the old version is rejected instead of overwriting.
    r = await admin.patch(admin.h(""), {"version": hotel["version"], "name": "Stale edit"})
    assert r.status_code == 409 and error_code(r) == "VERSION_CONFLICT"
    assert r.json()["error"]["params"]["current_version"] == body["version"]


async def test_hotel_reference_data_validation(admin: Api):
    v = (await admin.get(admin.h(""))).json()["version"]
    for payload, code in [
        ({"timezone": "Mars/Olympus"}, "INVALID_TIMEZONE"),
        ({"currency_code": "XYZ"}, "INVALID_CURRENCY"),
        ({"country_code": "ZZ"}, "INVALID_COUNTRY"),
        ({"supported_languages": ["fr", "ru"]}, "DEFAULT_LANGUAGE_NOT_SUPPORTED"),
        ({"social_links": {"myspace": "x"}}, "INVALID_SOCIAL_NETWORK"),
    ]:
        r = await admin.patch(admin.h(""), {"version": v, **payload})
        assert r.status_code == 422, payload
        assert r.json()["error"]["fields"][0]["code"] == code, payload


async def test_buildings_and_floors(admin: Api):
    b = (await admin.post(admin.h("/buildings"), {"code": "MAIN", "name": "Main building"})).json()
    r = await admin.post(admin.h("/buildings"), {"code": "MAIN", "name": "Duplicate"})
    assert r.status_code == 409 and error_code(r) == "BUILDING_CODE_EXISTS"
    assert r.json()["error"]["fields"][0]["loc"] == ["body", "code"]
    f1 = await admin.post(admin.h("/floors"), {"building_id": b["id"], "level": 1, "name": "1st"})
    assert f1.status_code == 201
    r = await admin.post(admin.h("/floors"), {"building_id": b["id"], "level": 1, "name": "Again"})
    assert error_code(r) == "FLOOR_LEVEL_EXISTS"
    # Can't delete a building that still has floors.
    r = await admin.delete(admin.h(f"/buildings/{b['id']}"))
    assert r.status_code == 409
    assert (await admin.delete(admin.h(f"/floors/{f1.json()['id']}"))).status_code == 204
    assert (await admin.delete(admin.h(f"/buildings/{b['id']}"))).status_code == 204


async def _room_type(admin: Api, code: str = "DBL", **extra) -> dict:
    payload = {
        "code": code,
        "name": {"en": "Double", "fr": "Double", "km": "បន្ទប់គ្រែពីរ"},
        "base_occupancy": 2,
        "max_occupancy": 3,
        "max_adults": 2,
        "max_children": 1,
        "bed_configuration": [{"type": "queen", "count": 1}],
        "base_price": "80.00",
        **extra,
    }
    r = await admin.post(admin.h("/room-types"), payload)
    assert r.status_code == 201, r.text
    return r.json()


async def test_room_categories(admin: Api):
    amenities = (await admin.get(admin.h("/amenities"))).json()
    assert len(amenities) >= 14  # defaults seeded, translated
    wifi = next(a for a in amenities if a["code"] == "wifi")
    assert set(wifi["name"]) == {"en", "fr", "zh-CN", "ru", "km"}

    rt = await _room_type(admin, amenity_ids=[wifi["id"]])
    assert rt["amenity_ids"] == [wifi["id"]] and rt["base_price"] == "80.00"

    r = await admin.post(
        admin.h("/room-types"),
        {
            "code": "BAD",
            "name": {"en": "Bad"},
            "base_occupancy": 3,
            "max_occupancy": 2,
            "max_adults": 2,
            "base_price": "10",
        },
    )
    assert r.status_code == 422 and error_code(r) == "MAX_OCCUPANCY_BELOW_BASE"
    r = await admin.post(admin.h("/room-types"), {"code": "NONAME", "name": {}, "base_price": "1"})
    assert r.status_code == 422
    # Partial update is validated against the merged values.
    r = await admin.patch(admin.h(f"/room-types/{rt['id']}"), {"version": rt["version"], "max_occupancy": 1})
    assert r.status_code == 422
    r = await admin.patch(
        admin.h(f"/room-types/{rt['id']}"),
        {"version": rt["version"], "base_price": "95.50", "amenity_ids": []},
    )
    assert r.status_code == 200 and r.json()["base_price"] == "95.50"
    assert r.json()["amenity_ids"] == []


async def test_rooms_single_and_bulk(admin: Api):
    rt = await _room_type(admin)
    b = (await admin.post(admin.h("/buildings"), {"code": "A", "name": "A"})).json()
    other = (await admin.post(admin.h("/buildings"), {"code": "B", "name": "B"})).json()
    floor = (await admin.post(admin.h("/floors"), {"building_id": b["id"], "level": 1, "name": "1"})).json()

    r = await admin.post(
        admin.h("/rooms"),
        {
            "room_type_id": rt["id"],
            "floor_id": floor["id"],
            "number": "100",
            "has_balcony": True,
            "view": "sea",
            "bathroom": "private_shower",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["building_id"] == b["id"]  # derived from the floor

    r = await admin.post(admin.h("/rooms"), {"room_type_id": rt["id"], "number": "100"})
    assert r.status_code == 409 and error_code(r) == "ROOM_NUMBER_EXISTS"

    r = await admin.post(
        admin.h("/rooms"),
        {"room_type_id": rt["id"], "number": "200", "building_id": other["id"], "floor_id": floor["id"]},
    )
    assert r.status_code == 422 and error_code(r) == "FLOOR_NOT_IN_BUILDING"

    r = await admin.post(
        admin.h("/rooms/bulk"), {"room_type_id": rt["id"], "floor_id": floor["id"], "start": 101, "end": 110}
    )
    assert r.status_code == 201 and len(r.json()) == 10
    r = await admin.post(admin.h("/rooms/bulk"), {"room_type_id": rt["id"], "start": 109, "end": 112})
    assert r.status_code == 409 and "109" in r.json()["error"]["params"]["numbers"]

    rooms = (await admin.get(admin.h("/rooms"))).json()
    assert [x["number"] for x in rooms][:3] == ["100", "101", "102"]  # natural order
    types = (await admin.get(admin.h("/room-types"))).json()
    assert types[0]["room_count"] == 11  # counted, never hardcoded

    # Deactivating removes from active counts; category with rooms can't be deleted.
    room = rooms[0]
    r = await admin.patch(admin.h(f"/rooms/{room['id']}"), {"version": room["version"], "is_active": False})
    assert r.status_code == 200
    assert (await admin.get(admin.h("/room-types"))).json()[0]["room_count"] == 10
    r = await admin.delete(admin.h(f"/room-types/{rt['id']}"))
    assert r.status_code == 409 and error_code(r) == "ROOM_TYPE_IN_USE"


async def test_facilities_services_and_taxes(admin: Api):
    r = await admin.post(
        admin.h("/facilities"),
        {
            "code": "POOL",
            "category": "pool",
            "name": {"en": "Pool", "zh-CN": "游泳池"},
            "opening_hours": {"mon": [["07:00", "21:00"]], "sat": [["18:00", "02:00"]]},
        },
    )
    assert r.status_code == 201, r.text
    pool = r.json()
    assert pool["opening_hours"]["sat"] == [["18:00", "02:00"]]
    r = await admin.post(
        admin.h("/facilities"), {"code": "X", "name": {"en": "X"}, "opening_hours": {"funday": []}}
    )
    assert r.status_code == 422
    r = await admin.post(
        admin.h("/facilities"), {"code": "SPA", "name": {"en": "Spa"}, "pricing_mode": "paid"}
    )
    assert r.status_code == 422 and error_code(r) == "PRICE_REQUIRED"

    r = await admin.post(
        admin.h("/services"),
        {"code": "BRK", "name": {"en": "Breakfast"}, "price": "12.00", "pricing_unit": "per_person_night"},
    )
    assert r.status_code == 201
    r = await admin.post(
        admin.h("/services"),
        {"code": "TOWEL", "name": {"en": "Pool towel"}, "price": "2", "facility_id": pool["id"]},
    )
    assert r.status_code == 201
    # Facility referenced by a service cannot be deleted.
    assert (await admin.delete(admin.h(f"/facilities/{pool['id']}"))).status_code == 409

    r = await admin.post(
        admin.h("/tax-rates"), {"code": "VAT", "name": {"en": "VAT"}, "kind": "percent", "rate": "10"}
    )
    assert r.status_code == 201 and r.json()["rate"] == "10.0000"
    r = await admin.post(
        admin.h("/tax-rates"), {"code": "BAD", "name": {"en": "Bad"}, "kind": "percent", "rate": "150"}
    )
    assert r.status_code == 422 and error_code(r) == "TAX_PERCENT_ABOVE_100"
    r = await admin.post(
        admin.h("/tax-rates"),
        {
            "code": "CITY",
            "name": {"en": "City tax"},
            "kind": "fixed_per_person_night",
            "rate": "1.5",
            "applies_to": "accommodation",
        },
    )
    assert r.status_code == 201


async def test_every_change_is_audited(admin: Api):
    rt = await _room_type(admin)
    await admin.patch(admin.h(f"/room-types/{rt['id']}"), {"version": rt["version"], "base_price": "99.00"})
    logs = (await admin.get(admin.h("/audit-logs"), params={"entity_type": "room_type"})).json()["items"]
    assert [entry["action"] for entry in logs] == ["room_type.update", "room_type.create"]
    assert logs[0]["changes"] == {"base_price": ["80.00", "99.00"]}
    assert logs[0]["user_id"] == admin.me["user"]["id"]
