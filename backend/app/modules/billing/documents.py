"""Localized billing documents (invoice, guest folio statement, payment receipt).

`build()` turns a folio statement into a language-specific, fully formatted
document (all strings and amounts already rendered with CLDR rules via Babel).
Invoices store this document as their immutable snapshot; the PDF template
only lays it out.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from functools import cache
from pathlib import Path
from typing import Any

from babel import Locale
from babel.dates import format_date, format_datetime
from babel.numbers import format_currency, format_decimal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.schemas import SUPPORTED_LANGUAGES
from app.modules.billing.folio import Statement, signed_base
from app.modules.billing.models import Payment
from app.modules.guests.models import Guest
from app.modules.hotels.models import Hotel
from app.modules.pricing.models import RatePlan
from app.modules.rooms.models import Room, RoomType

BABEL_LOCALES = {"en": "en", "fr": "fr", "zh-CN": "zh_Hans_CN", "ru": "ru", "km": "km_KH"}
I18N_DIR = Path(__file__).parent / "i18n"


@cache
def labels(lang: str) -> dict[str, Any]:
    return json.loads((I18N_DIR / f"{lang}.json").read_text(encoding="utf-8"))


class Tr:
    """Translator + formatter for one document language."""

    def __init__(self, lang: str, fallback: str) -> None:
        self.lang = lang
        self.fallback = fallback
        self.locale = BABEL_LOCALES[lang]
        self._labels = labels(lang)
        self._en = labels("en")

    def __call__(self, key: str, **params: Any) -> str:
        value: Any = self._labels
        for part in key.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        if value is None:
            value = self._en
            for part in key.split("."):
                value = value.get(part) if isinstance(value, dict) else None
        if isinstance(value, dict):  # plural forms
            form = Locale.parse(self.locale).plural_form(params.get("count", 0))
            value = value.get(form) or value.get("other", "")
        return str(value or key).format(**params)

    def text(self, localized: dict[str, str] | None) -> str:
        """Pick a LocalizedText value: document language, hotel language, English, any."""
        if not localized:
            return ""
        for code in (self.lang, self.fallback, "en"):
            if localized.get(code):
                return localized[code]
        return next(iter(localized.values()), "")

    def money(self, amount: Decimal, currency: str) -> str:
        return format_currency(amount, currency, locale=self.locale)

    def number(self, value: Decimal) -> str:
        return format_decimal(
            value.normalize() if value == value.to_integral() else value, locale=self.locale
        )

    def date(self, value: date) -> str:
        return format_date(value, format="medium", locale=self.locale)

    def datetime(self, value: Any, tz: str) -> str:
        return format_datetime(value, format="medium", tzinfo=tz, locale=self.locale)


def pick_language(requested: str | None, guest: Guest | None, hotel: Hotel) -> str:
    for lang in (requested, guest.preferred_language if guest else None, hotel.default_language, "en"):
        if lang in SUPPORTED_LANGUAGES:
            return lang
    return "en"


def guest_bill_to(guest: Guest) -> dict[str, Any]:
    out: dict[str, Any] = {"name": f"{guest.first_name} {guest.last_name}".strip()}
    for f in ("address", "city", "country_code", "email"):
        if getattr(guest, f):
            out[f] = getattr(guest, f)
    return out


def _hotel_block(hotel: Hotel, tr: Tr) -> dict[str, Any]:
    city = " ".join(x for x in (hotel.postal_code, hotel.city) if x)
    address = [x for x in (hotel.address_line1, hotel.address_line2, city, hotel.region) if x]
    if hotel.country_code:
        address.append(_country(hotel.country_code, tr))
    contact = [x for x in (hotel.phone, hotel.email, hotel.website) if x]
    return {
        "name": hotel.name,
        "legal_name": hotel.legal_name if hotel.legal_name and hotel.legal_name != hotel.name else None,
        "address": address,
        "contact": contact,
        "tax_id": tr("tax_id_value", tax_id=hotel.tax_id) if hotel.tax_id else None,
    }


def _country(code: str, tr: Tr) -> str:
    return Locale.parse(tr.locale).territories.get(code, code)


def _bill_to_block(bill_to: dict[str, Any], tr: Tr) -> list[str]:
    lines = [x for x in (bill_to.get("company"), bill_to.get("name")) if x]
    lines += [x for x in (bill_to.get("address"), bill_to.get("city")) if x]
    if bill_to.get("country_code"):
        lines.append(_country(bill_to["country_code"], tr))
    if bill_to.get("tax_id"):
        lines.append(tr("tax_id_value", tax_id=bill_to["tax_id"]))
    if bill_to.get("email"):
        lines.append(bill_to["email"])
    return lines


async def _lookups(db: AsyncSession, st: Statement) -> tuple[dict, dict, dict]:
    res = st.reservation
    type_ids = {rr.room_type_id for rr in res.rooms}
    room_ids = {rr.room_id for rr in res.rooms if rr.room_id}
    plan_ids = {rr.rate_plan_id for rr in res.rooms if rr.rate_plan_id}
    types = {t.id: t for t in await db.scalars(select(RoomType).where(RoomType.id.in_(type_ids)))}
    rooms = {r.id: r for r in await db.scalars(select(Room).where(Room.id.in_(room_ids)))} if room_ids else {}
    plans = (
        {p.id: p for p in await db.scalars(select(RatePlan).where(RatePlan.id.in_(plan_ids)))}
        if plan_ids
        else {}
    )
    return types, rooms, plans


def _payment_label(p: Payment, tr: Tr) -> str:
    label = f"{tr('payment_kind.' + p.kind)} · {tr('method.' + p.method)}"
    if p.card_brand or p.card_last4:
        label += " · " + tr(
            "card", brand=tr("card_brand." + (p.card_brand or "other")), last4=p.card_last4 or "····"
        )
    if p.reference:
        label += f" · {p.reference}"
    return label


def _payment_amount(p: Payment, base: str, tr: Tr) -> str:
    amount = tr.money(signed_base(p), base)
    if p.currency != base:
        amount += f" ({tr.money(p.amount, p.currency)})"
    return amount


async def build(
    db: AsyncSession,
    kind: str,
    lang: str,
    hotel: Hotel,
    st: Statement,
    *,
    bill_to: dict[str, Any],
    number: str | None = None,
    issue_date: date,
    payment: Payment | None = None,
) -> dict[str, Any]:
    tr = Tr(lang, hotel.default_language)
    res = st.reservation
    cur = res.currency
    types, rooms, plans = await _lookups(db, st)
    guest = await db.get(Guest, res.booker_guest_id)

    meta = [
        [tr("reservation"), res.code],
        [tr("guest"), f"{guest.first_name} {guest.last_name}" if guest else ""],
        [tr("stay"), f"{tr.date(res.arrival)} – {tr.date(res.departure)}"],
    ]
    room_numbers = sorted({rooms[rr.room_id].number for rr in res.rooms if rr.room_id in rooms})
    if room_numbers:
        meta.append([tr("rooms"), ", ".join(room_numbers)])

    doc: dict[str, Any] = {
        "kind": kind,
        "language": lang,
        "title": tr("title." + kind),
        "number": number,
        "issue_date": tr.date(issue_date),
        "hotel": _hotel_block(hotel, tr),
        "bill_to_label": tr("received_from" if kind == "receipt" else "bill_to"),
        "bill_to": _bill_to_block(bill_to, tr),
        "meta": meta,
        "labels": {
            k: tr(k)
            for k in (
                "number",
                "issue_date",
                "description",
                "quantity",
                "unit_price",
                "amount",
                "payments",
                "void_stamp",
            )
        },
        "page_css": _page_css(tr("page_of", page="\x00page", pages="\x00pages")),
        "lines": [],
        "totals": [],
        "payments": [],
        "notes": [],
    }

    if kind == "receipt":
        assert payment is not None
        rows = [
            [tr("receipt_amount"), tr.money(payment.amount, payment.currency)],
            [tr("receipt_method"), _payment_label(payment, tr)],
            [tr("receipt_date"), tr.datetime(payment.received_at, hotel.timezone)],
        ]
        if payment.currency != cur:
            rows.append(
                [
                    tr("exchange_rate"),
                    tr(
                        "exchange_value",
                        base=cur,
                        rate=tr.number(payment.exchange_rate),
                        currency=payment.currency,
                    ),
                ]
            )
            rows.append([tr("equivalent"), tr.money(payment.amount_base, cur)])
        doc["receipt"] = rows
        doc["is_void"] = payment.is_void
        doc["totals"] = [
            [tr("total"), tr.money(res.grand_total, cur), False],
            [tr("paid"), tr.money(res.paid_total, cur), False],
            _balance_row(res.grand_total - res.paid_total, cur, tr),
        ]
        if payment.notes:
            doc["notes"].append(payment.notes)
        return doc

    for run in st.accommodation:
        rt = types.get(run.room_type_id)
        plan = plans.get(run.rate_plan_id) if run.rate_plan_id else None
        description = tr.text(rt.name) if rt else ""
        if plan:
            description += f" · {tr.text(plan.name)}"
        room = rooms.get(run.room_id) if run.room_id else None
        detail = [tr("room_number", number=room.number) if room else tr("room_unassigned")]
        detail.append(f"{tr.date(run.start)} – {tr.date(run.end)}")
        detail.append(tr("nights", count=run.nights))
        doc["lines"].append(
            {
                "description": description,
                "detail": " · ".join(detail),
                "quantity": tr.number(Decimal(run.nights)),
                "unit_price": tr.money(run.unit_price, cur),
                "amount": tr.money(run.amount, cur),
                "void": False,
            }
        )
    for c in st.charges:
        if c.kind == "service":
            description = tr.text(c.name) or c.description or ""
            detail = c.description if c.name and c.description else ""
        elif c.kind == "fee":
            description = tr("fee." + (c.fee_type or "other"))
            detail = c.description or ""
        else:
            description = tr("adjustment")
            detail = c.description or ""
        detail = " · ".join(x for x in (tr.date(c.service_date), detail) if x)
        if c.is_void:
            if kind == "invoice":
                continue  # voided charges are not part of an invoice
            detail += f" · {tr('voided')}: {c.void_reason}"
        doc["lines"].append(
            {
                "description": description,
                "detail": detail,
                "quantity": tr.number(c.quantity),
                "unit_price": tr.money(c.unit_price, cur),
                "amount": tr.money(c.amount, cur),
                "void": c.is_void,
            }
        )

    subtotal = res.accommodation_total + res.charges_total
    totals = [[tr("subtotal"), tr.money(subtotal, cur), False]]
    for t in res.tax_breakdown:
        name = tr.text(t.get("name")) or t["code"]
        if t.get("kind") == "percent":
            name += f" {tr.number(Decimal(t['rate']))}%"
        amount = tr.money(Decimal(t["amount"]), cur)
        if t["is_inclusive"]:
            totals.append([tr("tax_included", name=name), amount, False])
        else:
            totals.append([name, amount, False])
    totals.append([tr("total"), tr.money(res.grand_total, cur), True])
    totals.append([tr("paid"), tr.money(res.paid_total, cur), False])
    totals.append(_balance_row(res.grand_total - res.paid_total, cur, tr))
    doc["totals"] = totals
    doc["payments"] = [
        {
            "date": tr.date(p.received_at.astimezone(hotel.zone).date()),
            "number": p.number,
            "label": _payment_label(p, tr),
            "amount": _payment_amount(p, cur, tr),
        }
        for p in st.payments
        if not p.is_void
    ]
    if kind == "statement":
        doc["notes"].append(tr("statement_note"))
    doc["notes"].append(tr("thanks"))
    return doc


def _page_css(template: str) -> str:
    """'Page {page} of {pages}' -> a CSS content value using page counters."""
    parts = []
    for i, chunk in enumerate(template.split("\x00")):
        if i:
            name = "pages" if chunk.startswith("pages") else "page"
            parts.append(f"counter({name})")
            chunk = chunk[len(name) :]
        if chunk:
            parts.append(json.dumps(chunk, ensure_ascii=False))
    return " ".join(parts)


def _balance_row(balance: Decimal, currency: str, tr: Tr) -> list[Any]:
    if balance < 0:
        return [tr("credit_balance"), tr.money(-balance, currency), True]
    return [tr("balance_due"), tr.money(balance, currency), True]
