"""Company accounts (city ledger): direct billing authorised on a booking, the
balance transferred to the company at departure with an invoice made out to
it, payments from the company applied to its open invoices, aging, and the
day's cash-up (a transfer is not money received)."""

from __future__ import annotations

import io
from datetime import timedelta
from decimal import Decimal

from pypdf import PdfReader
from sqlalchemy import text

from app.core.db import owner_sessionmaker
from tests.conftest import Api, error_code
from tests.test_billing import book, hotel, pay, today  # noqa: F401  (fixture)

ACCOUNT = {
    "code": "MEKONG",
    "name": "Mekong Relief",
    "legal_name": "Mekong Relief Organisation",
    "tax_id": "K001-123456789",
    "address": "12 Street 240",
    "city": "Phnom Penh",
    "country_code": "KH",
    "email": "finance@mekong-relief.example",
    "payment_terms_days": 30,
    "credit_limit": "1000.00",
}


async def account(admin: Api, **extra) -> dict:
    r = await admin.post(admin.h("/company-accounts"), {**ACCOUNT, **extra})
    assert r.status_code == 201, r.text
    return r.json()


async def reservation(admin: Api, res_id: str) -> dict:
    return (await admin.get(admin.h(f"/reservations/{res_id}"))).json()


async def bill_to_company(admin: Api, res: dict, account_id: str):
    res = await reservation(admin, res["id"])
    return await admin.patch(
        admin.h(f"/reservations/{res['id']}"), {"version": res["version"], "company_account_id": account_id}
    )


async def transfer(api: Api, res: dict, **body):
    return await api.post(api.h(f"/reservations/{res['id']}/transfer-to-account"), body)


async def detail(api: Api, account_id: str) -> dict:
    r = await api.get(api.h(f"/company-accounts/{account_id}"))
    assert r.status_code == 200, r.text
    return r.json()


async def test_accounts_and_permissions(admin: Api, user_factory):
    acc = await account(admin)
    assert (acc["balance"], acc["open_items"], acc["currency"]) == ("0.00", 0, "USD")
    r = await admin.post(admin.h("/company-accounts"), {**ACCOUNT, "name": "Again"})
    assert r.status_code == 409 and error_code(r) == "ACCOUNT_CODE_EXISTS"

    clerk = await user_factory("receptionist")
    assert [a["code"] for a in (await clerk.get(clerk.h("/company-accounts"))).json()] == ["MEKONG"]
    r = await clerk.post(clerk.h("/company-accounts"), {**ACCOUNT, "code": "X"})
    assert r.status_code == 403
    accountant = await user_factory("accountant")
    r = await accountant.patch(
        accountant.h(f"/company-accounts/{acc['id']}"), {"version": acc["version"], "payment_terms_days": 45}
    )
    assert r.status_code == 200 and r.json()["payment_terms_days"] == 45
    maid = await user_factory("housekeeping")
    assert (await maid.get(maid.h("/company-accounts"))).status_code == 403
    found = (await admin.get(admin.h("/company-accounts"), params={"q": "relief"})).json()
    assert [a["code"] for a in found] == ["MEKONG"]
    # Never used: it can be deleted (otherwise it is deactivated).
    assert (await admin.delete(admin.h(f"/company-accounts/{acc['id']}"))).status_code == 204


async def test_balance_transferred_to_the_company_at_departure(admin: Api, hotel):  # noqa: F811
    acc = await account(admin)
    res = await book(admin, hotel, 0, 2)
    r = await transfer(admin, res)
    assert r.status_code == 409 and error_code(r) == "NO_COMPANY_ACCOUNT"

    r = await bill_to_company(admin, res, acc["id"])
    assert r.status_code == 200 and r.json()["company_account_id"] == acc["id"]
    assert (await pay(admin, res, amount="20.00")).status_code == 201  # the guest paid a deposit
    owed = Decimal((await reservation(admin, res["id"]))["balance"])
    assert owed > 0

    r = await transfer(admin, res)
    assert r.status_code == 200, r.text
    assert Decimal((await reservation(admin, res["id"]))["balance"]) == 0
    moved = next(p for p in r.json()["payments"] if p["method"] == "city_ledger")
    assert Decimal(moved["amount"]) == owed and moved["number"].startswith("CL-")
    invoice = r.json()["invoices"][0]
    # The invoice was made out just before the transfer: it shows what the company owes.
    assert r.json()["invoice_outdated"] is False
    assert Decimal(r.json()["totals"]["transferred"]) == owed
    assert invoice["bill_to"]["company"] == "Mekong Relief Organisation"
    # Only the guest's own payment can be refunded, never the amount transferred.
    refund = await pay(admin, res, kind="refund", amount="25.00")
    assert refund.status_code == 409 and refund.json()["error"]["params"]["max"] == "20.00"
    assert invoice["bill_to"]["tax_id"] == "K001-123456789"

    d = await detail(admin, acc["id"])
    assert Decimal(d["balance"]) == owed and d["open_items"] == 1
    item = d["items"][0]
    assert (item["invoice_number"], item["reservation_code"]) == (invoice["number"], res["code"])
    assert item["due_date"] == (today() + timedelta(days=30)).isoformat()
    assert Decimal(item["open"]) == owed and Decimal(d["aging"]["current"]) == owed

    r = await transfer(admin, res)
    assert r.status_code == 409 and error_code(r) == "NOTHING_TO_TRANSFER"


async def test_credit_limit_invoice_to_the_company_and_inactive_accounts(admin: Api, hotel):  # noqa: F811
    acc = await account(admin, credit_limit="100.00")
    big = await book(admin, hotel, 0, 5)
    await bill_to_company(admin, big, acc["id"])
    r = await transfer(admin, big)
    assert r.status_code == 409 and error_code(r) == "CREDIT_LIMIT_EXCEEDED"
    assert r.json()["error"]["params"]["limit"] == "100.00"

    # An invoice already made out to the guest: void it, then transfer.
    small = await book(admin, hotel, 0, 1, room=1)
    inv = await admin.post(admin.h(f"/reservations/{small['id']}/invoices"), {})
    assert inv.status_code == 201
    await bill_to_company(admin, small, acc["id"])
    r = await transfer(admin, small)
    assert r.status_code == 409 and error_code(r) == "INVOICE_NOT_TO_COMPANY"
    await admin.post(admin.h(f"/invoices/{inv.json()['id']}/void"), {"reason": "To the company"})
    assert (await transfer(admin, small)).status_code == 200

    a = await detail(admin, acc["id"])
    r = await admin.patch(
        admin.h(f"/company-accounts/{acc['id']}"), {"version": a["version"], "is_active": False}
    )
    assert r.status_code == 200
    other = await book(admin, hotel, 0, 1, room=2)
    r = await bill_to_company(admin, other, acc["id"])
    assert r.status_code == 422 and r.json()["error"]["fields"][0]["code"] == "ACCOUNT_NOT_AVAILABLE"


async def test_company_payments_allocation_aging_and_voids(admin: Api, hotel, user_factory):  # noqa: F811
    acc = await account(admin, credit_limit=None)
    transfers = []
    for room, nights in ((0, 1), (1, 2)):
        res = await book(admin, hotel, 0, nights, room=room)
        await bill_to_company(admin, res, acc["id"])
        r = await transfer(admin, res)
        assert r.status_code == 200, r.text
        transfers.append((res, next(p for p in r.json()["payments"] if p["method"] == "city_ledger")))
    (res1, t1), (res2, t2) = transfers
    a1, a2 = Decimal(t1["amount"]), Decimal(t2["amount"])
    # The first one fell due 45 days ago (as if transferred two months back).
    async with owner_sessionmaker()() as db:
        await db.execute(text("ALTER TABLE payments DISABLE TRIGGER trg_payments_immutable"))
        await db.execute(
            text("UPDATE payments SET due_date = CAST(:d AS date) WHERE id = :p"),
            {"d": today() - timedelta(days=45), "p": t1["id"]},
        )
        await db.execute(text("ALTER TABLE payments ENABLE TRIGGER trg_payments_immutable"))
        await db.commit()
    d = await detail(admin, acc["id"])
    assert Decimal(d["aging"]["days_31_60"]) == a1 and Decimal(d["aging"]["current"]) == a2
    assert Decimal(d["overdue"]) == a1

    # A bank transfer covering the first invoice and part of the second: oldest first.
    clerk = await user_factory("receptionist")
    paid = a1 + Decimal("10.00")
    r = await clerk.post(
        clerk.h(f"/company-accounts/{acc['id']}/payments"),
        {"method": "bank_transfer", "amount": str(paid), "reference": "ABA 7781"},
    )
    assert r.status_code == 201, r.text
    d = r.json()
    open_by_id = {i["transfer_id"]: Decimal(i["open"]) for i in d["items"]}
    assert open_by_id == {t1["id"]: Decimal(0), t2["id"]: a2 - Decimal("10.00")}
    assert Decimal(d["balance"]) == a2 - Decimal("10.00") and Decimal(d["overdue"]) == 0
    first = d["payments"][0]
    assert first["number"].startswith("RC-") and Decimal(first["unallocated"]) == 0
    assert {a["transfer_id"]: Decimal(a["amount"]) for a in first["allocations"]} == {
        t1["id"]: a1,
        t2["id"]: Decimal("10.00"),
    }

    # Paying more than owed leaves a credit; an allocation beyond the open amount is refused.
    r = await admin.post(
        admin.h(f"/company-accounts/{acc['id']}/payments"),
        {
            "method": "cash",
            "amount": "5000.00",
            "allocations": [{"transfer_id": t2["id"], "amount": "9999.00"}],
        },
    )
    assert r.status_code == 422 and error_code(r) == "ALLOCATION_EXCEEDS_OPEN"
    r = await admin.post(
        admin.h(f"/company-accounts/{acc['id']}/payments"), {"method": "cash", "amount": "5000.00"}
    )
    assert r.status_code == 201 and Decimal(r.json()["balance"]) < 0
    maid = await user_factory("housekeeping")
    r = await maid.post(maid.h(f"/company-accounts/{acc['id']}/payments"), {"method": "cash", "amount": "1"})
    assert r.status_code == 403

    # A transfer the company paid part of cannot be voided; voiding the payment reopens it.
    r = await admin.post(admin.h(f"/reservations/{res1['id']}/payments/{t1['id']}/void"), {"reason": "Wrong"})
    assert r.status_code == 409 and error_code(r) == "TRANSFER_HAS_PAYMENTS"
    for p in (await detail(admin, acc["id"]))["payments"]:
        r = await admin.post(
            admin.h(f"/company-accounts/{acc['id']}/payments/{p['id']}/void"), {"reason": "Bounced"}
        )
        assert r.status_code == 200, r.text
    d = await detail(admin, acc["id"])
    assert Decimal(d["balance"]) == a1 + a2 and all(p["is_void"] for p in d["payments"])
    r = await admin.post(admin.h(f"/reservations/{res1['id']}/payments/{t1['id']}/void"), {"reason": "Wrong"})
    assert r.status_code == 200
    assert Decimal((await reservation(admin, res1["id"]))["balance"]) == a1  # back on the folio
    assert Decimal((await detail(admin, acc["id"]))["balance"]) == a2


async def test_cash_up_counts_company_money_once(admin: Api, hotel):  # noqa: F811
    acc = await account(admin, credit_limit=None)
    res = await book(admin, hotel, 0, 1)
    await bill_to_company(admin, res, acc["id"])
    await pay(admin, res, amount="5.00")
    moved = Decimal(
        next(p for p in (await transfer(admin, res)).json()["payments"] if p["method"] == "city_ledger")[
            "amount"
        ]
    )
    r = await admin.post(
        admin.h(f"/company-accounts/{acc['id']}/payments"), {"method": "bank_transfer", "amount": "30.00"}
    )
    assert r.status_code == 201
    day = (await admin.get(admin.h("/night-audit"), params={"date": today().isoformat()})).json()["report"]
    sources = {(p["source"], p["method"]): Decimal(p["amount_base"]) for p in day["payments"]}
    assert sources == {("folio", "cash"): Decimal("5.00"), ("accounts", "bank_transfer"): Decimal("30.00")}
    assert Decimal(day["payments_net"]) == Decimal("35.00")  # the transfer is not money received
    assert day["transfers"]["count"] == 1 and Decimal(day["transfers"]["total"]) == moved
    report = (await admin.get(admin.h("/payments"), params={"start": today().isoformat()})).json()
    assert Decimal(report["net_base"]) == Decimal("5.00")  # front-desk payments: the transfer excluded


async def test_statement_pdf(admin: Api, hotel):  # noqa: F811
    acc = await account(admin, language="fr")
    res = await book(admin, hotel, 0, 1)
    await bill_to_company(admin, res, acc["id"])
    invoice = (await transfer(admin, res)).json()["invoices"][0]
    r = await admin.get(admin.h(f"/company-accounts/{acc['id']}/statement.pdf"))
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    words = "".join(page.extract_text() for page in PdfReader(io.BytesIO(r.content)).pages)
    assert "Relevé de compte" in words and invoice["number"] in words and "Mekong Relief" in words
