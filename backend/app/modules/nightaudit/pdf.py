"""PDF of a closed day's report, in the reader's language (same renderer,
fonts and number formats as the billing documents)."""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from app.modules.billing.documents import Tr, _hotel_block, _page_css
from app.modules.billing.pdf import DEFAULT_FONTS, FONTS, _render_sync
from app.modules.hotels.models import Hotel
from app.modules.nightaudit.models import DayClosure

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html"]),
)


def _money(tr: Tr, value: Any, currency: str) -> str:
    return "—" if value is None else tr.money(Decimal(str(value)), currency)


def _pct(tr: Tr, value: Any) -> str:
    return "—" if value is None else f"{tr.number(Decimal(str(value)))} %"


def document(
    hotel: Hotel, closure: DayClosure, report: dict[str, Any], closed_by: str | None, lang: str
) -> dict:
    tr = Tr(lang, hotel.default_language)
    cur = report["currency"]
    rooms, mv = report["rooms"], report["movements"]
    sections: list[dict[str, Any]] = [
        {
            "title": tr("day_report.rooms"),
            "rows": [
                (tr("day_report.available"), str(rooms["available"])),
                (tr("day_report.out_of_service"), str(rooms["out_of_service"])),
                (tr("day_report.sold"), str(rooms["sold"])),
                (tr("day_report.occupancy"), _pct(tr, rooms["occupancy"])),
            ]
            + (
                [
                    (tr("day_report.room_revenue"), _money(tr, rooms["revenue"], cur)),
                    ("ADR", _money(tr, rooms["adr"], cur)),
                    ("RevPAR", _money(tr, rooms["revpar"], cur)),
                ]
                if report.get("revenue") is not None
                else []
            ),
        },
        {
            "title": tr("day_report.movements"),
            "rows": [
                (tr(f"day_report.{k}"), str(mv[k]))
                for k in (
                    "arrivals",
                    "departures",
                    "walk_ins",
                    "no_shows",
                    "bookings_made",
                    "cancellations",
                    "arrivals_tomorrow",
                )
            ]
            + [(tr("day_report.occupancy_tomorrow"), _pct(tr, mv["occupancy_tomorrow"]))],
        },
    ]
    revenue = report.get("revenue")
    if revenue is not None:
        sections.append(
            {
                "title": tr("day_report.revenue"),
                "rows": [
                    (tr(f"day_report.dept.{k}"), _money(tr, revenue[k], cur))
                    for k in ("rooms", "restaurant", "vehicles", "services", "fees", "adjustments")
                ],
                "total": (tr("day_report.total"), _money(tr, revenue["total"], cur)),
            }
        )
    if report.get("payments_net") is not None:
        rows = [
            (
                f"{tr(f'day_report.source.{p["source"]}')} · {tr(f'method.{p["method"]}')}"
                + (f" · {tr(f'payment_kind.{p["kind"]}')}" if p["kind"] != "payment" else ""),
                f"{p['count']} × · {_money(tr, p['amount'], p['currency'])}",
            )
            for p in report["payments"]
        ]
        sections.append(
            {
                "title": tr("day_report.payments"),
                "rows": rows or [(tr("day_report.no_payments"), "")],
                "total": (tr("day_report.net"), _money(tr, report["payments_net"], cur)),
            }
        )
        inv = report["invoices"]
        sections.append(
            {
                "title": tr("day_report.invoices"),
                "rows": [
                    (tr("day_report.issued"), f"{inv['issued']} · {_money(tr, inv['total'], cur)}"),
                    (tr("day_report.voided"), str(inv["voided"])),
                ],
            }
        )
    items = closure.open_items
    open_rows = []
    for key in ("not_arrived", "not_departed", "unassigned_tomorrow"):
        for s in items.get(key, []):
            open_rows.append(
                (
                    tr(f"day_report.open.{key}"),
                    f"{s['code']} · {s['guest_name']}"
                    + (f" · {s['room_number']}" if s.get("room_number") else ""),
                )
            )
    for c in items.get("open_checks", []):
        open_rows.append(
            (tr("day_report.open.open_checks"), f"{c['number']} · {_money(tr, c['total'], cur)}")
        )
    for r in items.get("overdue_rentals", []):
        open_rows.append((tr("day_report.open.overdue_rentals"), f"{r['number']} · {r['vehicle']}"))
    balances = items.get("balances_due", {})
    if balances.get("count"):
        open_rows.append(
            (
                tr("day_report.open.balances_due"),
                f"{balances['count']} · {_money(tr, balances['total'], cur)}",
            )
        )
    sections.append(
        {"title": tr("day_report.open_items"), "rows": open_rows or [(tr("day_report.nothing_open"), "")]}
    )

    business_date = closure.business_date
    return {
        "language": lang,
        "title": tr("day_report.title"),
        "hotel": _hotel_block(hotel, tr),
        "meta": [
            (
                tr("day_report.business_date"),
                tr.date(
                    business_date if isinstance(business_date, date) else date.fromisoformat(business_date)
                ),
            ),
            (
                tr("day_report.closed_at"),
                tr.datetime(
                    closure.closed_at
                    if isinstance(closure.closed_at, datetime)
                    else datetime.fromisoformat(closure.closed_at),
                    hotel.timezone,
                ),
            ),
            (tr("day_report.closed_by"), closed_by or "—"),
        ],
        "sections": sections,
        "notes": closure.notes,
        "notes_label": tr("day_report.notes"),
        "page_css": _page_css(tr("page_of", page="\x00page", pages="\x00pages")),
    }


def render_html(doc: dict[str, Any]) -> str:
    page_css = str(doc.get("page_css", '""')).replace("<", "\\3C ")
    return _env.get_template("day_report.html").render(
        doc=doc,
        page_css=Markup(page_css),  # noqa: S704 - built from our own translation files, '<' escaped
        fonts=Markup(FONTS.get(doc["language"], DEFAULT_FONTS)),  # noqa: S704 - constant
        line_height="1.6" if doc["language"] == "km" else "1.4",
    )


async def render_pdf(doc: dict[str, Any]) -> bytes:
    return await asyncio.to_thread(_render_sync, render_html(doc))
