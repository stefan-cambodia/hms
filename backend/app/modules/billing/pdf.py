"""PDF rendering of billing documents (WeasyPrint: HarfBuzz shaping, so Khmer
and Chinese render correctly with the Noto fonts installed on the server)."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html"]),
)
# Fontconfig/Pango are not reliably thread-safe: render one document at a time.
_lock = threading.Lock()

FONTS = {
    "km": "'Noto Sans Khmer', 'Noto Sans', 'Noto Sans CJK SC', sans-serif",
    "zh-CN": "'Noto Sans CJK SC', 'Noto Sans SC', 'Noto Sans', sans-serif",
}
DEFAULT_FONTS = "'Noto Sans', 'Noto Sans Khmer', 'Noto Sans CJK SC', sans-serif"


def _deny_fetch(url: str, *args: Any, **kwargs: Any) -> dict:
    # Documents are self-contained: never let the renderer fetch anything.
    raise ValueError(f"external resource refused: {url[:80]}")


def render_html(doc: dict[str, Any], *, void: bool = False) -> str:
    from markupsafe import Markup

    page_css = str(doc.get("page_css", '""')).replace("<", "\\3C ")
    return _env.get_template("document.html").render(
        doc=doc,
        void=void,
        page_css=Markup(page_css),  # noqa: S704 - built from our own translation files, '<' escaped
        fonts=Markup(FONTS.get(doc["language"], DEFAULT_FONTS)),  # noqa: S704 - constant
        line_height="1.6" if doc["language"] == "km" else "1.4",
    )


def _render_sync(html: str) -> bytes:
    from weasyprint import HTML

    with _lock:
        return HTML(string=html, url_fetcher=_deny_fetch).write_pdf()


async def render_pdf(doc: dict[str, Any], *, void: bool = False) -> bytes:
    return await asyncio.to_thread(_render_sync, render_html(doc, void=void))
