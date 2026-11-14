"""Split folios: a booking billed to a company that pays the room only. The
company's part holds the nights, their taxes and the room fees; the guest's
part the other charges. Each part has its own payments and its own invoice;
only the company's part goes to its account; the parts add up to the folio."""

from __future__ import annotations

import io
from decimal import Decimal

from pypdf import PdfReader

from tests.conftest import Api, error_code
from tests.test_accounts import account, bill_to_company, reservation, transfer
from tests.test_billing import book, charge, folio, hotel, pay  # noqa: F401  (fixture)


async def company_pays(admin: Api, res: dict, what: str):
    res = await reservation(admin, res["id"])
    body = {"version": res["version"], "company_pays": what}
    return await admin.patch(admin.h(f"/reservations/{res['id']}"), body)


async def move(api: Api, res: dict, charge_id: str, part: str):
    return await api.post(api.h(f"/reservations/{res['id']}/charges/{charge_id}/folio"), {"folio": part})


def pdf_text(content: bytes) -> str:
    return " ".join(page.extract_text() for page in PdfReader(io.BytesIO(content)).pages)


async def test_company_pays_the_room_the_guest_the_extras(admin: Api, hotel):  # noqa: F811
    acc = await account(admin)
    res = await book(admin, hotel, 0, 2)  # 2 nights: 100.00 + VAT 10.00 + city tax 4.00
    await bill_to_company(admin, res, acc["id"])
    r = await company_pays(admin, res, "room")
    assert r.status_code == 200 and r.json()["company_pays"] == "room"

    await charge(admin, res, service_id=hotel["breakfast"], quantity="2")  # 24.00 + VAT 2.40
    await charge(admin, res, kind="fee", fee_type="late_checkout", unit_price="20.00")  # a room fee
    r = await charge(admin, res, description="Laundry", unit_price="7.50")  # + VAT 0.75
    laundry = next(c for c in r.json()["charges"] if c["description"] == "Laundry")
    f = await folio(admin, res)
    assert {c["kind"]: c["folio"] for c in f["charges"] if c["kind"] != "service"} == {"fee": "company"}
    assert {c["folio"] for c in f["charges"] if c["kind"] == "service"} == {"guest"}
    assert f["parts"]["guest"]["grand_total"] == "34.65"  # breakfast and laundry
    assert f["parts"]["company"]["grand_total"] == "134.00"  # the room and the late check-out

    # The company also pays the laundry (moved by hand); the parts still add up.
    r = await move(admin, res, laundry["id"], "company")
    assert r.status_code == 200, r.text
    f = r.json()
    company, guest = f["parts"]["company"], f["parts"]["guest"]
    assert (guest["grand_total"], company["grand_total"]) == ("26.40", "142.25")
    assert company["accommodation"] == "100.00" and company["charges"] == "27.50"
    both = Decimal(guest["grand_total"]) + Decimal(company["grand_total"])
    assert both == Decimal(f["totals"]["grand_total"])

    # The guest pays their part; it is invoiced to them alone.
    assert (await pay(admin, res, amount="26.40")).status_code == 201
    r = await admin.post(admin.h(f"/reservations/{res['id']}/invoices"), {})
    assert r.status_code == 422 and error_code(r) == "FOLIO_REQUIRED"
    r = await admin.post(admin.h(f"/reservations/{res['id']}/invoices"), {"folio": "guest", "language": "en"})
    assert r.status_code == 201, r.text
    guest_invoice = r.json()
    assert (guest_invoice["folio"], guest_invoice["total"]) == ("guest", "26.40")
    assert guest_invoice["balance"] == "0.00"
    assert guest_invoice["bill_to"]["name"] == "Sophea Chan"
    text = pdf_text((await admin.get(admin.h(f"/invoices/{guest_invoice['id']}/pdf"))).content)
    assert "Laundry" not in text and "the room is billed to Mekong Relief Organisation" in text

    # Only the company's part goes to its account, with an invoice made out to it.
    r = await transfer(admin, res, language="en")
    assert r.status_code == 200, r.text
    f = r.json()
    moved = next(p for p in f["payments"] if p["method"] == "city_ledger")
    assert (moved["amount"], moved["folio"]) == ("142.25", "company")
    company_invoice = next(i for i in f["invoices"] if i["folio"] == "company")
    assert company_invoice["total"] == "142.25"
    assert company_invoice["bill_to"]["company_account_id"] == acc["id"]
    assert f["invoice_outdated"] is False and f["totals"]["balance"] == "0.00"
    assert (f["parts"]["company"]["balance"], f["parts"]["guest"]["balance"]) == ("0.00", "0.00")
    text = pdf_text((await admin.get(admin.h(f"/invoices/{company_invoice['id']}/pdf"))).content)
    assert "Laundry" in text and "Breakfast" not in text and "billed to Mekong Relief Organisation" in text

    # The guest can only get back what they paid on their part.
    r = await pay(admin, res, kind="refund", amount="30.00")
    assert r.status_code == 409 and r.json()["error"]["params"]["max"] == "26.40"
    # Who pays what is settled once the company was billed.
    r = await company_pays(admin, res, "all")
    assert r.status_code == 409 and error_code(r) == "TRANSFERRED_TO_COMPANY"
    # The company's invoice cannot be voided while the company owes it.
    r = await admin.post(admin.h(f"/invoices/{company_invoice['id']}/void"), {"reason": "Mistake"})
    assert r.status_code == 409 and error_code(r) == "INVOICE_TRANSFERRED"

    # Moving the breakfast to the company now: its invoice no longer matches,
    # and nothing more goes to the company until it is re-issued.
    breakfast = next(c for c in f["charges"] if c["kind"] == "service" and c["folio"] == "guest")
    f = (await move(admin, res, breakfast["id"], "company")).json()
    assert f["invoice_outdated"] is True and f["parts"]["guest"]["balance"] == "-26.40"
    r = await transfer(admin, res)
    assert r.status_code == 409 and error_code(r) == "INVOICE_OUTDATED"
    f = (await move(admin, res, breakfast["id"], "guest")).json()
    assert f["invoice_outdated"] is False

    acc_detail = (await admin.get(admin.h(f"/company-accounts/{acc['id']}"))).json()
    assert acc_detail["balance"] == "142.25"


async def test_split_folio_rules(admin: Api, hotel, user_factory):  # noqa: F811
    acc = await account(admin)
    res = await book(admin, hotel, 0, 1)
    r = await charge(admin, res, description="Minibar", unit_price="5.00")
    minibar = r.json()["charges"][0]
    # Not split: one folio, no parts, charges cannot be moved.
    f = await folio(admin, res)
    assert f["parts"] is None and f["charges"][0]["folio"] is None
    r = await move(admin, res, minibar["id"], "company")
    assert r.status_code == 409 and error_code(r) == "FOLIO_NOT_SPLIT"
    r = await company_pays(admin, res, None)
    assert r.status_code == 422
    # One invoice for everything, then the folio is split: it must be re-issued per part.
    inv = (await admin.post(admin.h(f"/reservations/{res['id']}/invoices"), {})).json()
    assert inv["folio"] == "all"
    await bill_to_company(admin, res, acc["id"])
    await company_pays(admin, res, "room")
    f = await folio(admin, res)
    assert f["parts"]["guest"]["grand_total"] == "5.50" and f["invoice_outdated"] is False
    r = await admin.post(admin.h(f"/reservations/{res['id']}/invoices"), {"folio": "guest"})
    assert r.status_code == 409 and error_code(r) == "INVOICE_ALREADY_ISSUED"
    assert r.json()["error"]["params"]["number"] == inv["number"]
    r = await transfer(admin, res)
    assert r.status_code == 409 and error_code(r) == "INVOICE_NOT_TO_COMPANY"
    await admin.post(admin.h(f"/invoices/{inv['id']}/void"), {"reason": "Split bill"})

    # A payment on the company's part (its representative paid at the desk).
    r = await pay(admin, res, amount="10.00", folio="company")
    assert r.status_code == 201 and r.json()["folio"] == "company"
    f = await folio(admin, res)
    assert f["parts"]["company"]["paid_total"] == "10.00" and f["parts"]["guest"]["paid_total"] == "0.00"
    receipt = await admin.get(admin.h(f"/reservations/{res['id']}/payments/{r.json()['id']}/receipt.pdf"))
    assert receipt.status_code == 200
    statement = await admin.get(
        admin.h(f"/reservations/{res['id']}/folio.pdf"), params={"folio": "guest", "language": "en"}
    )
    text = pdf_text(statement.content)
    assert "Minibar" in text and "Standard" not in text

    # Checking out: what goes to the company and what the guest owes.
    r = await admin.post(
        admin.h(f"/reservations/{res['id']}/check-in"),
        {"version": (await reservation(admin, res["id"]))["version"], "ignore_room_status": True},
    )
    assert r.status_code == 200, r.text
    r = await admin.post(
        admin.h(f"/reservations/{res['id']}/check-out"),
        {"version": r.json()["version"], "shorten_stay": True},
    )
    assert r.status_code == 409 and error_code(r) == "BALANCE_DUE"
    params = r.json()["error"]["params"]
    company = Decimal(f["parts"]["company"]["balance"])
    assert Decimal(params["company_balance"]) == company and params["guest_balance"] == "5.50"

    # A receptionist can move a charge; the room nights always stay with the company.
    clerk = await user_factory("receptionist")
    assert (await move(clerk, res, minibar["id"], "company")).status_code == 200
    f = await folio(admin, res)
    assert f["parts"]["guest"]["grand_total"] == "0.00"
