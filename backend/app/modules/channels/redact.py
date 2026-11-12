"""Remove payment card data and credentials from provider messages before
they are stored in the message log (security strategy §4.3, channel manager
§3.3). Applied to every logged body, whatever the provider."""

from __future__ import annotations

import re

from app.core.schemas import mask_card_numbers

MAX_LOGGED = 64 * 1024

# XML elements and attributes that carry secrets or card data (OTA and
# WS-Security vocabulary). CardHolderName is kept (a name, not card data).
_SECRET_ELEMENTS = re.compile(
    r"(<(?:[\w.-]+:)?(Password|CardNumber|SeriesCode|PlainText|CVV|CVC|CardSecurityCode)\b[^>]*>)(.*?)"
    r"(</(?:[\w.-]+:)?\2\s*>)",
    re.DOTALL | re.IGNORECASE,
)
_SECRET_ATTRIBUTES = re.compile(
    r"\b(CardNumber|SeriesCode|CVV|CVC|Password|EncryptedValue|Token)\s*=\s*(\"[^\"]*\"|'[^']*')",
    re.IGNORECASE,
)
_JSON_SECRETS = re.compile(
    r"(\"(?:password|cardNumber|card_number|cvv|cvc|securityCode)\"\s*:\s*)(\"[^\"]*\"|\d+)", re.IGNORECASE
)


def redact(body: str | bytes | None) -> str | None:
    if body is None:
        return None
    text = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else body
    text = _SECRET_ELEMENTS.sub(lambda m: f"{m.group(1)}***{m.group(4)}", text)
    text = _SECRET_ATTRIBUTES.sub(lambda m: f'{m.group(1)}="***"', text)
    text = _JSON_SECRETS.sub(lambda m: f'{m.group(1)}"***"', text)
    text = mask_card_numbers(text, "***")
    if len(text) > MAX_LOGGED:
        text = text[:MAX_LOGGED] + f"\n… truncated ({len(text) - MAX_LOGGED} more characters)"
    return text
