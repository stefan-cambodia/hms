"""Phase 5 — folio, payments (multi-currency), invoices and receipts (PDF in
5 languages), cancellation and no-show fees."""

from __future__ import annotations

import asyncio
import io
import os
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from pypdf import PdfReader
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core import sequences
from app.core.db import sessionmaker
from tests.conftest import Api, error_code
from tests.test_reservations import _parallel_clients


def today() -> date:
    return datetime.now(ZoneInfo("Asia/Phnom_Penh")).date()


def d(offset: int) -> str:
    return (today() + timedelta(days=offset)).isoformat()


@pytest.fixture
async def hotel(admin: Api) -> dict:
    """STD at 50.00; VAT 10% on everything, city tax 1.00 per person-night on rooms;
    breakfast 12.00 per person-night; KHR accepted at 4,100 per USD."""
    rt = (
        await admin.post(
            admin.h("/room-types"),
            {
                "code": "STD",
                "name": {"en": "Standard", "km": "បន្ទប់ស្តង់ដារ", "zh-CN": "标准间"},
                "base_occupancy": 2,
                "max_occupancy": 3,
                "max_adults": 3,
                "max_children": 1,
                "base_price": "50.00",
            },
        )
    ).json()
    rooms = (
        await admin.post(admin.h("/rooms/bulk"), {"room_type_id": rt["id"], "start": 101, "end": 104})
    ).json()
    await admin.post(
        admin.h("/tax-rates"), {"code": "VAT", "name": {"en": "VAT"}, "kind": "percent", "rate": "10"}
    )
    await admin.post(
        admin.h("/tax-rates"),
        {
            "code": "CITY",
            "name": {"en": "City tax"},
            "kind": "fixed_per_person_night",
            "rate": "1.00",
            "applies_to": "accommodation",
        },
    )
    breakfast = (
        await admin.post(
            admin.h("/services"),
            {
                "code": "BRK",
                "name": {"en": "Breakfast", "km": "អាហារពេលព្រឹក", "fr": "Petit-déjeuner"},
                "price": "12.00",
                "pricing_unit": "per_person_night",
            },
        )
    ).json()
    khr = await admin.post(admin.h("/currencies"), {"code": "KHR", "units_per_base": "4100"})
    assert khr.status_code == 201, khr.text
    return {
        "rt": rt["id"],
        "rooms": [r["id"] for r in rooms],
        "breakfast": breakfast["id"],
        "khr": khr.json(),
    }


async def book(api: Api, hotel: dict, arrival: int, departure: int, room: int = 0, **extra) -> dict:
    r = await api.post(
        api.h("/reservations"),
        {
            "arrival": d(arrival),
            "departure": d(departure),
            "guest": {"first_name": "Sophea", "last_name": "Chan", "preferred_language": "km"},
            "rooms": [{"room_type_id": hotel["rt"], "room_id": hotel["rooms"][room], "adults": 2}],
            "override_restrictions": True,
            **extra,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


async def folio(api: Api, res: dict) -> dict:
    r = await api.get(api.h(f"/reservations/{res['id']}/folio"))
    assert r.status_code == 200, r.text
    return r.json()


async def charge(api: Api, res: dict, **body):
    return await api.post(api.h(f"/reservations/{res['id']}/charges"), body)


async def pay(api: Api, res: dict, **body):
    return await api.post(api.h(f"/reservations/{res['id']}/payments"), {"method": "cash", **body})


async def test_folio_balance_math(admin: Api, hotel):
    res = await book(admin, hotel, 5, 7)
    # Accommodation 2 x 50; VAT 10.00; city tax 2 persons x 2 nights = 4.00.
    assert res["grand_total"] == "114.00"

    r = await charge(admin, res, service_id=hotel["breakfast"], quantity="2")
    assert r.status_code == 201, r.text
    f = r.json()
    brk = f["charges"][0]
    assert brk["name"]["en"] == "Breakfast" and brk["unit_price"] == "12.00" and brk["amount"] == "24.00"
    assert brk["tax_amount"] == "2.40"  # services pay VAT, not the city tax
    r = await charge(admin, res, kind="fee", fee_type="late_checkout", unit_price="20.00")
    assert r.status_code == 201, r.text
    r = await charge(admin, res, kind="adjustment", description="Goodwill", unit_price="-10.00")
    assert r.status_code == 201, r.text
    r = await charge(admin, res, description="Laundry", unit_price="7.50")  # free-text item
    assert r.status_code == 201, r.text

    f = await folio(admin, res)
    t = f["totals"]
    assert t["accommodation"] == "100.00"
    assert t["charges"] == "41.50"  # 24 + 20 - 10 + 7.50
    assert {x["code"]: x["amount"] for x in f["taxes"]} == {"VAT": "13.15", "CITY": "4.00"}
    assert t["tax_total"] == "17.15" and t["grand_total"] == "158.65"

    assert (await pay(admin, res, amount="50.00")).status_code == 201
    r = await pay(admin, res, amount="82000", currency="KHR", exchange_rate="4100")
    assert r.status_code == 201, r.text
    khr = r.json()
    assert khr["amount_base"] == "20.00" and khr["exchange_rate"] == "4100.000000"
    assert khr["number"] == "RC-000002"
    r = await pay(admin, res, kind="refund", amount="5.00")
    assert r.status_code == 201

    f = await folio(admin, res)
    assert f["totals"]["paid_total"] == "65.00" and f["totals"]["balance"] == "93.65"

    # Voids never delete: they are kept, flagged, and leave the totals.
    fee = next(c for c in f["charges"] if c["kind"] == "fee")
    r = await admin.post(
        admin.h(f"/reservations/{res['id']}/charges/{fee['id']}/void"), {"reason": "Waived by manager"}
    )
    assert r.status_code == 200, r.text
    f = r.json()
    assert f["totals"]["grand_total"] == "138.65"
    assert next(c for c in f["charges"] if c["id"] == fee["id"])["is_void"] is True
    r = await admin.post(admin.h(f"/reservations/{res['id']}/charges/{fee['id']}/void"), {"reason": "again"})
    assert r.status_code == 409 and error_code(r) == "ALREADY_VOID"
    r = await admin.post(
        admin.h(f"/reservations/{res['id']}/payments/{khr['id']}/void"), {"reason": "Wrong reservation"}
    )
    assert r.status_code == 200 and r.json()["totals"]["paid_total"] == "45.00"

    # The reservation shows the same numbers, and its history lists every step.
    full = (await admin.get(admin.h(f"/reservations/{res['id']}"))).json()
    assert full["grand_total"] == "138.65" and full["paid_total"] == "45.00" and full["balance"] == "93.65"
    actions = [e["action"] for e in (await admin.get(admin.h(f"/reservations/{res['id']}/events"))).json()]
    assert actions.count("charge_posted") == 4 and actions.count("payment_recorded") == 3
    assert "charge_voided" in actions and "payment_voided" in actions


async def test_currencies_and_exchange_rates(admin: Api, hotel, user_factory):
    res = await book(admin, hotel, 5, 6)
    r = await pay(admin, res, amount="10", currency="EUR")
    assert r.status_code == 422 and error_code(r) == "CURRENCY_NOT_ACCEPTED"
    r = await admin.post(admin.h("/currencies"), {"code": "USD", "units_per_base": "1"})
    assert r.status_code == 422 and error_code(r) == "BASE_CURRENCY"
    r = await admin.post(admin.h("/currencies"), {"code": "KHR", "units_per_base": "4000"})
    assert r.status_code == 409 and error_code(r) == "CURRENCY_EXISTS"

    # The rate changes while a clerk has the payment form open.
    khr = hotel["khr"]
    r = await admin.patch(
        admin.h(f"/currencies/{khr['id']}"), {"version": khr["version"], "units_per_base": "4050"}
    )
    assert r.status_code == 200
    r = await pay(admin, res, amount="41000", currency="KHR", exchange_rate="4100")
    assert r.status_code == 409 and error_code(r) == "EXCHANGE_RATE_CHANGED"
    assert r.json()["error"]["params"] == {"currency": "KHR", "rate": "4050.000000"}
    r = await pay(admin, res, amount="40500", currency="KHR", exchange_rate="4050")
    assert r.status_code == 201 and r.json()["amount_base"] == "10.00"
    # Too small to be worth one cent.
    r = await pay(admin, res, amount="10", currency="KHR")
    assert r.status_code == 422 and error_code(r) == "AMOUNT_TOO_SMALL"

    receptionist = await user_factory("receptionist")
    r = await receptionist.post(receptionist.h("/currencies"), {"code": "THB", "units_per_base": "36"})
    assert r.status_code == 403
    accountant = await user_factory("accountant")
    r = await accountant.post(accountant.h("/currencies"), {"code": "THB", "units_per_base": "36"})
    assert r.status_code == 201
    assert [c["code"] for c in (await receptionist.get(receptionist.h("/currencies"))).json()] == [
        "KHR",
        "THB",
    ]


async def test_refund_limits_and_permissions(admin: Api, hotel, user_factory):
    res = await book(admin, hotel, 5, 6)
    assert (await pay(admin, res, amount="30.00")).status_code == 201
    r = await pay(admin, res, kind="refund", amount="30.01")
    assert r.status_code == 409 and error_code(r) == "REFUND_EXCEEDS_PAID"

    receptionist = await user_factory("receptionist")
    r = await pay(receptionist, res, kind="refund", amount="5.00")
    assert r.status_code == 403
    r = await charge(receptionist, res, kind="adjustment", description="Discount", unit_price="-5.00")
    assert r.status_code == 403
    r = await charge(receptionist, res, service_id=hotel["breakfast"])
    assert r.status_code == 201
    charge_id = r.json()["charges"][0]["id"]
    r = await receptionist.post(
        receptionist.h(f"/reservations/{res['id']}/charges/{charge_id}/void"), {"reason": "x"}
    )
    assert r.status_code == 403
    accountant = await user_factory("accountant")
    r = await accountant.post(
        accountant.h(f"/reservations/{res['id']}/charges/{charge_id}/void"), {"reason": "Posted twice"}
    )
    assert r.status_code == 200
    reservation_manager = await user_factory("reservation_manager")
    assert (
        await reservation_manager.get(reservation_manager.h(f"/reservations/{res['id']}/folio"))
    ).status_code == 200
    r = await pay(reservation_manager, res, amount="1.00")
    assert r.status_code == 403


async def test_card_numbers_are_never_stored(admin: Api, hotel):
    res = await book(admin, hotel, 5, 6)
    r = await pay(admin, res, method="card", amount="10.00", reference="4111 1111 1111 1111")
    assert r.status_code == 422 and r.json()["error"]["fields"][0]["code"] == "card_number_not_allowed"
    r = await pay(admin, res, method="card", amount="10.00", card_last4="41111")
    assert r.status_code == 422
    r = await pay(admin, res, amount="10.00", card_last4="1111")  # card details on a cash payment
    assert r.status_code == 422
    r = await pay(
        admin, res, method="card", amount="10.00", card_brand="visa", card_last4="1111", reference="AUTH 0042"
    )
    assert r.status_code == 201
    r = await admin.patch(
        admin.h(f"/reservations/{res['id']}"),
        {"version": res["version"] + 1, "internal_notes": "Guarantee card 5555-5555-5555-4444 exp 12/29"},
    )
    assert r.status_code == 422 and r.json()["error"]["fields"][0]["code"] == "card_number_not_allowed"
    r = await charge(admin, res, description="Card 4111111111111111", unit_price="1.00")
    assert r.status_code == 422


async def test_payment_idempotency(admin: Api, hotel):
    res = await book(admin, hotel, 5, 6)
    key = str(uuid.uuid4())
    body = {"method": "cash", "amount": "25.00"}
    url = admin.h(f"/reservations/{res['id']}/payments")
    first = await admin.post(url, body, headers={"Idempotency-Key": key})
    retry = await admin.post(url, body, headers={"Idempotency-Key": key})
    assert first.status_code == retry.status_code == 201
    assert first.json()["id"] == retry.json()["id"]
    other = await admin.post(url, {**body, "amount": "26.00"}, headers={"Idempotency-Key": key})
    assert other.status_code == 409 and error_code(other) == "IDEMPOTENCY_KEY_REUSED"

    # Concurrent retries of one request: still a single payment.
    key2 = str(uuid.uuid4())
    results = await asyncio.gather(
        *(admin.post(url, body, headers={"Idempotency-Key": key2}) for _ in range(5))
    )
    assert {r.status_code for r in results} == {201} and len({r.json()["id"] for r in results}) == 1
    f = await folio(admin, res)
    assert len(f["payments"]) == 2 and f["totals"]["paid_total"] == "50.00"


async def test_concurrent_postings_keep_totals_exact(admin: Api, hotel):
    res = await book(admin, hotel, 5, 6)

    apis = await _parallel_clients(admin, 8)
    try:
        results = await asyncio.gather(*(pay(api, res, amount="1.00") for api in apis))
    finally:
        for api in apis:
            await api.client.aclose()
    assert all(r.status_code == 201 for r in results), [r.text for r in results if r.status_code != 201]
    numbers = sorted(r.json()["number"] for r in results)
    assert numbers == [f"RC-{i:06d}" for i in range(1, 9)]
    f = await folio(admin, res)
    assert f["totals"]["paid_total"] == "8.00"


async def test_financial_rows_are_immutable(admin: Api, hotel):
    res = await book(admin, hotel, 5, 6)
    p = (await pay(admin, res, amount="10.00")).json()
    async with sessionmaker()() as db:
        with pytest.raises((IntegrityError, DBAPIError), match="financial_row_immutable|only void fields"):
            await db.execute(text("UPDATE payments SET amount = 1 WHERE id = :i"), {"i": p["id"]})
        await db.rollback()
        with pytest.raises((IntegrityError, DBAPIError), match="never deleted"):
            await db.execute(text("DELETE FROM payments WHERE id = :i"), {"i": p["id"]})
        await db.rollback()
        await db.execute(
            text("UPDATE payments SET is_void = true, void_reason = 'x' WHERE id = :i"), {"i": p["id"]}
        )
        await db.commit()
        with pytest.raises((IntegrityError, DBAPIError), match="cannot be restored"):
            await db.execute(
                text("UPDATE payments SET is_void = false, void_reason = NULL WHERE id = :i"), {"i": p["id"]}
            )
        await db.rollback()


async def test_invoice_numbers_are_gapless(admin: Api, hotel):
    reservations = [await book(admin, hotel, 5 + i, 6 + i, room=i % 4) for i in range(5)]
    # A transaction that takes a number and then fails gives it back.
    async with sessionmaker()() as db:
        assert await sequences.next_value(db, uuid.UUID(admin.hotel_id), "invoice") == 1
        await db.rollback()
    results = await asyncio.gather(
        *(admin.post(admin.h(f"/reservations/{r['id']}/invoices"), {"language": "en"}) for r in reservations)
    )
    assert all(r.status_code == 201 for r in results), [r.text for r in results]
    assert sorted(r.json()["number"] for r in results) == [f"INV-{i:06d}" for i in range(1, 6)]

    first = results[0].json()
    again = await admin.post(admin.h(f"/reservations/{first['reservation_id']}/invoices"), {})
    assert again.status_code == 409 and error_code(again) == "INVOICE_ALREADY_ISSUED"
    r = await admin.post(admin.h(f"/invoices/{first['id']}/void"), {"reason": "Wrong company name"})
    assert r.status_code == 200 and r.json()["status"] == "void"
    r = await admin.post(
        admin.h(f"/reservations/{first['reservation_id']}/invoices"),
        {"bill_to": {"name": "Sophea Chan", "company": "Mekong Trading Co.", "tax_id": "K001-901234567"}},
    )
    assert r.status_code == 201 and r.json()["number"] == "INV-000006"
    listed = (await admin.get(admin.h("/invoices"), params={"q": "Mekong"})).json()
    assert [i["number"] for i in listed["items"]] == ["INV-000006"]
    voided = (await admin.get(admin.h("/invoices"), params={"status": "void"})).json()
    assert voided["total"] == 1


def pdf_text_and_fonts(content: bytes, name: str | None = None) -> tuple[str, set[str]]:
    assert content[:5] == b"%PDF-"
    if name and os.environ.get("HMS_TEST_PDF_DIR"):  # keep samples for visual review
        Path(os.environ["HMS_TEST_PDF_DIR"], f"{name}.pdf").write_bytes(content)
    reader = PdfReader(io.BytesIO(content))
    fonts: set[str] = set()
    for page in reader.pages:
        for f in (page["/Resources"].get("/Font") or {}).values():
            fonts.add(str(f.get_object()["/BaseFont"]))
    return "\n".join(page.extract_text() for page in reader.pages), fonts


async def test_invoice_snapshot_and_khmer_pdf(admin: Api, hotel):
    res = await book(admin, hotel, 5, 7)
    await charge(admin, res, service_id=hotel["breakfast"], quantity="2")
    await pay(admin, res, amount="410000", currency="KHR")
    # The guest prefers Khmer: the invoice is issued in Khmer by default.
    r = await admin.post(admin.h(f"/reservations/{res['id']}/invoices"), {})
    assert r.status_code == 201, r.text
    inv = r.json()
    assert inv["language"] == "km" and inv["total"] == "140.40" and inv["paid_total"] == "100.00"
    assert inv["balance"] == "40.40"

    pdf = await admin.get(admin.h(f"/invoices/{inv['id']}/pdf"))
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    content, fonts = pdf_text_and_fonts(pdf.content, "invoice-km")
    assert any("NotoSansKhmer" in f.replace("-", "") for f in fonts), fonts
    # Text extraction scrambles Khmer pre-base vowels (rendering is correct, see
    # docs), so the PDF check uses words without them; the stored snapshot is
    # checked in full.
    flat = content.replace(" ", "")
    for word in ("វិក្កយបត្រ", "សរុប", inv["number"]):
        assert word in flat, word
    async with sessionmaker()() as db:
        doc = (
            await db.execute(text("SELECT document FROM invoices WHERE id = :i"), {"i": inv["id"]})
        ).scalar()
    assert doc["title"] == "វិក្កយបត្រ" and doc["language"] == "km"
    assert [line["description"] for line in doc["lines"]] == ["បន្ទប់ស្តង់ដារ · តម្លៃល្អបំផុត", "អាហារពេលព្រឹក"]
    assert doc["lines"][0]["detail"].endswith("2 យប់")
    assert doc["totals"][-1] == ["សមតុល្យត្រូវបង់", "40.40$", True]

    # Later folio changes never alter an issued invoice; the folio flags it.
    await charge(admin, res, kind="fee", fee_type="damage", unit_price="15.00")
    f = await folio(admin, res)
    assert f["invoice_outdated"] is True and f["invoices"][0]["total"] == "140.40"
    again = await admin.get(admin.h(f"/invoices/{inv['id']}/pdf"))
    assert pdf_text_and_fonts(again.content)[0] == content


@pytest.mark.parametrize(
    ("language", "title", "font"),
    [
        ("en", "Guest folio", "NotoSans"),
        ("fr", "Relevé de compte client", "NotoSans"),
        ("ru", "Выписка по счёту гостя", "NotoSans"),
        ("zh-CN", "客人账单", "NotoSansCJK"),
        ("km", "តារាងគណនីភ្ញៀវ", "NotoSansKhmer"),
    ],
)
async def test_folio_and_receipt_pdfs_in_every_language(admin: Api, hotel, language, title, font):
    res = await book(admin, hotel, 5, 6)
    p = (await pay(admin, res, method="card", amount="20.00", card_brand="visa", card_last4="4242")).json()
    r = await admin.get(admin.h(f"/reservations/{res['id']}/folio.pdf"), params={"language": language})
    assert r.status_code == 200, r.text
    content, fonts = pdf_text_and_fonts(r.content, f"folio-{language}")
    assert title.replace(" ", "") in content.replace(" ", "").replace("\n", "")
    assert any(font in f.replace("-", "") for f in fonts), fonts
    r = await admin.get(
        admin.h(f"/reservations/{res['id']}/payments/{p['id']}/receipt.pdf"), params={"language": language}
    )
    assert r.status_code == 200
    content, _ = pdf_text_and_fonts(r.content, f"receipt-{language}")
    assert p["number"] in content and "4242" in content


async def test_cancellation_fees_follow_the_policy(admin: Api, hotel, user_factory):
    # BAR uses FLEX: free until 1 day before arrival, then 1 night.
    early = await book(admin, hotel, 5, 8)
    preview = (await admin.get(admin.h(f"/reservations/{early['id']}/fee-preview"))).json()
    assert preview["fee"] == "0.00" and preview["stays"][0]["free_until"] == d(4)
    r = await admin.post(
        admin.h(f"/reservations/{early['id']}/cancel"),
        {"version": early["version"], "reason": "Plans changed"},
    )
    assert r.status_code == 200 and r.json()["grand_total"] == "0.00"

    late = await book(admin, hotel, 0, 3, room=1)  # arrival today: inside the penalty period
    preview = (await admin.get(admin.h(f"/reservations/{late['id']}/fee-preview"))).json()
    assert preview["fee"] == "50.00"
    receptionist = await user_factory("receptionist")
    r = await receptionist.post(
        receptionist.h(f"/reservations/{late['id']}/cancel"),
        {"version": late["version"], "reason": "Flight cancelled", "waive_fee": True},
    )
    assert r.status_code == 403  # waiving a fee needs folio.adjust
    r = await receptionist.post(
        receptionist.h(f"/reservations/{late['id']}/cancel"),
        {"version": late["version"], "reason": "Flight cancelled"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "cancelled" and body["accommodation_total"] == "0.00"
    assert body["charges_total"] == "50.00" and body["grand_total"] == "50.00" and body["balance"] == "50.00"
    f = await folio(admin, late)
    assert [(c["kind"], c["fee_type"], c["amount"]) for c in f["charges"]] == [
        ("fee", "cancellation", "50.00")
    ]
    # The released room is bookable again.
    await book(admin, hotel, 0, 3, room=1)

    # A non-refundable plan owes the whole stay; a manager may waive it.
    plans = (await admin.get(admin.h("/rate-plans"))).json()
    policies = (await admin.get(admin.h("/cancellation-policies"))).json()
    bar = next(p for p in plans if p["code"] == "BAR")
    nonref = (
        await admin.post(
            admin.h("/rate-plans"),
            {
                "code": "NRF",
                "name": {"en": "Non-refundable"},
                "is_refundable": False,
                "cancellation_policy_id": next(p["id"] for p in policies if p["code"] == "NONREF"),
                "parent_rate_plan_id": bar["id"],
                "derive_mode": "percent",
                "derive_value": "-10",
            },
        )
    ).json()
    nr = await admin.post(
        admin.h("/reservations"),
        {
            "arrival": d(20),
            "departure": d(22),
            "guest": {"first_name": "Li", "last_name": "Wei"},
            "rooms": [{"room_type_id": hotel["rt"], "adults": 2, "rate_plan_id": nonref["id"]}],
        },
    )
    nr = nr.json()
    preview = (await admin.get(admin.h(f"/reservations/{nr['id']}/fee-preview"))).json()
    assert preview["fee"] == "90.00" and preview["stays"][0]["refundable"] is False
    r = await admin.post(
        admin.h(f"/reservations/{nr['id']}/cancel"),
        {"version": nr["version"], "reason": "Goodwill", "waive_fee": True},
    )
    assert r.status_code == 200 and r.json()["grand_total"] == "0.00"
    events = (await admin.get(admin.h(f"/reservations/{nr['id']}/events"))).json()
    status_event = next(e for e in events if e["action"] == "status_changed")
    assert status_event["details"]["fee"] == "90.00" and status_event["details"]["fee_waived"] is True


async def test_no_show_fee(admin: Api, hotel):
    res = await book(admin, hotel, 0, 3)
    preview = (
        await admin.get(admin.h(f"/reservations/{res['id']}/fee-preview"), params={"action": "no_show"})
    ).json()
    assert preview["fee"] == "50.00"
    r = await admin.post(admin.h(f"/reservations/{res['id']}/no-show"), {"version": res["version"]})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "no_show" and r.json()["balance"] == "50.00"
    # Settling the fee on a closed reservation is allowed.
    assert (await pay(admin, res, amount="50.00", method="card")).status_code == 201


async def test_payments_report(admin: Api, hotel):
    a = await book(admin, hotel, 5, 6)
    b = await book(admin, hotel, 5, 6, room=1)
    await pay(admin, a, amount="30.00")
    await pay(admin, b, amount="20.00", method="card")
    await pay(admin, b, amount="41000", currency="KHR")
    voided = (await pay(admin, a, amount="99.00")).json()
    await admin.post(admin.h(f"/reservations/{a['id']}/payments/{voided['id']}/void"), {"reason": "typo"})
    await pay(admin, a, kind="refund", amount="5.00")

    report = (await admin.get(admin.h("/payments"), params={"start": d(0), "end": d(0)})).json()
    assert report["total"] == 4
    rows = {(s["method"], s["currency"], s["kind"]): s for s in report["summary"]}
    assert rows[("cash", "USD", "payment")]["amount"] == "30.00"
    assert rows[("cash", "KHR", "payment")]["amount"] == "41000.00"
    assert rows[("cash", "KHR", "payment")]["amount_base"] == "10.00"
    assert rows[("cash", "USD", "refund")]["amount"] == "5.00"
    assert Decimal(report["net_base"]) == Decimal("55.00")
    with_void = (await admin.get(admin.h("/payments"), params={"include_void": "true"})).json()
    assert with_void["total"] == 5
    assert report["items"][0]["guest_name"] == "Sophea Chan"
