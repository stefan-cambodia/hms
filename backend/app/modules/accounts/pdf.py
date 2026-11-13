"""Statement of account of a company: its open invoices, aging and balance,
in the company's language (same renderer, fonts and logo as the invoices)."""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import HotelContext
from app.core.money import ZERO
from app.modules.accounts import service
from app.modules.billing import service as billing
from app.modules.billing.documents import Tr, _country, _page_css, hotel_block
from app.modules.billing.pdf import DEFAULT_FONTS, FONTS, _render_sync, logo_src
from app.modules.media.service import document_logo

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html"]),
)
AGING = ("current", "days_1_30", "days_31_60", "days_61_90", "days_over_90")


async def statement(
    db: AsyncSession, ctx: HotelContext, account_id: uuid.UUID, language: str | None
) -> tuple[bytes, str]:
    data = await service.detail(db, ctx, account_id)
    hotel = await service._hotel(db, ctx.hotel_id)
    lang = language or data["language"] or hotel.default_language
    tr = Tr(lang, hotel.default_language)
    cur = data["currency"]
    money = lambda v: tr.money(Decimal(v), cur)  # noqa: E731
    company = [x for x in (data["legal_name"] or data["name"], data["contact_name"], data["address"]) if x]
    city = " ".join(x for x in (data["city"],) if x)
    if city:
        company.append(city)
    if data["country_code"]:
        company.append(_country(data["country_code"], tr))
    if data["tax_id"]:
        company.append(tr("tax_id_value", tax_id=data["tax_id"]))
    open_items = [i for i in data["items"] if i["open"] > ZERO]
    credit = -data["balance"] if data["balance"] < ZERO else ZERO
    bank = (hotel.billing_info or {}).get("bank_details")
    doc: dict[str, Any] = {
        "language": lang,
        "title": tr("account_statement.title"),
        "hotel": await hotel_block(db, hotel, tr),
        "meta": [
            (tr("account_statement.date"), tr.date(billing.hotel_today(hotel))),
            (tr("account_statement.account"), data["code"]),
            (
                tr("account_statement.terms"),
                tr("account_statement.terms_days", days=data["payment_terms_days"]),
            ),
        ],
        "company": company,
        "columns": [
            tr("account_statement.invoice"),
            tr("account_statement.invoice_date"),
            tr("guest"),
            tr("account_statement.due_date"),
            tr("amount"),
            tr("paid"),
            tr("account_statement.open"),
        ],
        "lines": [
            {
                "invoice": i["invoice_number"],
                "date": tr.date(i["date"]),
                "guest": f"{i['guest_name']} · {i['reservation_code']}",
                "due": tr.date(i["due_date"]),
                "amount": money(i["amount"]),
                "paid": money(i["paid"]),
                "open": money(i["open"]),
                "late": i["days_overdue"] > 0,
            }
            for i in sorted(open_items, key=lambda i: i["due_date"])
        ],
        "nothing_open": tr("account_statement.nothing_open"),
        "aging": [(tr(f"account_statement.{k}"), money(data["aging"][k])) for k in AGING],
        "totals": [
            *([(tr("account_statement.credit"), money(credit))] if credit > ZERO else []),
            (tr("account_statement.total_due"), money(max(data["balance"], ZERO))),
        ],
        "notes": [n for n in (tr("account_statement.please_pay"), bank) if n],
        "page_css": _page_css(tr("page_of", page="\x00page", pages="\x00pages")),
    }
    html = _env.get_template("statement.html").render(
        doc=doc,
        logo_src=logo_src(await document_logo(db, doc)),
        page_css=Markup(str(doc["page_css"]).replace("<", "\\3C ")),  # noqa: S704 - our own translations
        fonts=Markup(FONTS.get(lang, DEFAULT_FONTS)),  # noqa: S704 - constant
        line_height="1.6" if lang == "km" else "1.4",
    )
    content = await asyncio.to_thread(_render_sync, html)
    return content, f"statement-{data['code']}"
