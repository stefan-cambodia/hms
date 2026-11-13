"""PDF rendering of billing documents (WeasyPrint: HarfBuzz shaping, so Khmer
and Chinese render correctly with the Noto fonts installed on the server)."""

from __future__ import annotations

import asyncio
import base64
import logging
import threading
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import ImageFile
from sqlalchemy.ext.asyncio import AsyncSession
from weasyprint import HTML
from weasyprint.urls import URLFetcher

# Importing WeasyPrint sets Pillow's process-wide LOAD_TRUNCATED_IMAGES, which
# would make photo uploads accept truncated files (padded with grey). Our
# documents only embed our own re-encoded logo, never a truncated image:
# switch it back off, once, now that the import is done.
ImageFile.LOAD_TRUNCATED_IMAGES = False

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html"]),
)
# The renderer logs every layout step at INFO: keep only warnings in the API logs.
for _name in ("weasyprint", "weasyprint.progress", "fontTools"):
    logging.getLogger(_name).setLevel(logging.WARNING)

# Fontconfig/Pango are not reliably thread-safe: render one document at a time.
_lock = threading.Lock()

FONTS = {
    "km": "'Noto Sans Khmer', 'Noto Sans', 'Noto Sans CJK SC', sans-serif",
    "zh-CN": "'Noto Sans CJK SC', 'Noto Sans SC', 'Noto Sans', sans-serif",
}
DEFAULT_FONTS = "'Noto Sans', 'Noto Sans Khmer', 'Noto Sans CJK SC', sans-serif"


def _fetcher() -> URLFetcher:
    # Documents are self-contained: the only resource they may use is the
    # hotel logo, embedded as a data: URL. Never a file, never the network.
    return URLFetcher(allowed_protocols={"data"})


def logo_src(logo: tuple[bytes, str] | None) -> str | None:
    if logo is None:
        return None
    data, content_type = logo
    return f"data:{content_type};base64,{base64.b64encode(data).decode('ascii')}"


def render_html(doc: dict[str, Any], *, void: bool = False, logo: tuple[bytes, str] | None = None) -> str:
    from markupsafe import Markup

    page_css = str(doc.get("page_css", '""')).replace("<", "\\3C ")
    return _env.get_template("document.html").render(
        doc=doc,
        void=void,
        logo_src=logo_src(logo),
        page_css=Markup(page_css),  # noqa: S704 - built from our own translation files, '<' escaped
        fonts=Markup(FONTS.get(doc["language"], DEFAULT_FONTS)),  # noqa: S704 - constant
        line_height="1.6" if doc["language"] == "km" else "1.4",
    )


def _render_sync(html: str) -> bytes:
    with _lock:
        return HTML(string=html, url_fetcher=_fetcher()).write_pdf()


async def render_pdf(db: AsyncSession, doc: dict[str, Any], *, void: bool = False) -> bytes:
    from app.modules.media.service import document_logo

    logo = await document_logo(db, doc)
    return await asyncio.to_thread(_render_sync, render_html(doc, void=void, logo=logo))
