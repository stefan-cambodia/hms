"""Shared Pydantic types used by every module's schemas."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Annotated, Generic, Literal, TypeVar, get_args

from email_validator import EmailNotValidError, validate_email
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
)
from pydantic_core import PydanticCustomError

LanguageCode = Literal["en", "fr", "zh-CN", "ru", "km"]
SUPPORTED_LANGUAGES: tuple[str, ...] = get_args(LanguageCode)


def _clean_localized(value: dict[str, str]) -> dict[str, str]:
    # Drop blank translations so "missing" is always represented by absence.
    return {k: v.strip() for k, v in value.items() if v and v.strip()}


LocalizedName = Annotated[
    dict[LanguageCode, Annotated[str, StringConstraints(max_length=200)]],
    AfterValidator(_clean_localized),
]
LocalizedText = Annotated[
    dict[LanguageCode, Annotated[str, StringConstraints(max_length=10_000)]],
    AfterValidator(_clean_localized),
]


def _require_one(value: dict[str, str]) -> dict[str, str]:
    if not value:
        raise ValueError("at least one translation is required")
    return value


RequiredLocalizedName = Annotated[LocalizedName, AfterValidator(_require_one)]


def _staff_email(value: str) -> str:
    # Staff accounts may live on internal domains (hotel.lan, .local, .internal):
    # validate syntax only, never deliverability or "global" reachability.
    try:
        result = validate_email(value, check_deliverability=False, globally_deliverable=False)
    except EmailNotValidError as exc:
        # email-validator refuses ".local" (an mDNS special-use name) in every
        # mode, yet many hotel networks use it (e.g. Windows domains "hotel.local").
        # Check the syntax with a neutral internal suffix, keep the real domain.
        local, _, domain = value.strip().rpartition("@")
        if not (local and domain.lower().endswith(".local") and len(domain) > 6):
            raise ValueError("invalid email address") from exc
        try:
            probe = validate_email(
                f"{local}@{domain[:-6]}.lan", check_deliverability=False, globally_deliverable=False
            )
        except EmailNotValidError as exc2:
            raise ValueError("invalid email address") from exc2
        return f"{probe.local_part}@{probe.domain[:-4]}.local"
    return result.normalized


StaffEmail = Annotated[str, StringConstraints(max_length=320), AfterValidator(_staff_email)]

# --- card data guard (PCI DSS: never store a primary account number) -------------

_DIGIT_RUN = re.compile(r"\d(?:[ \-]?\d){12,18}")


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def contains_card_number(value: str) -> bool:
    """True when the text contains something that looks like a payment card
    number (13-19 digits, optionally grouped, passing the Luhn check)."""
    for match in _DIGIT_RUN.finditer(value):
        digits = re.sub(r"\D", "", match.group())
        if 13 <= len(digits) <= 19 and _luhn_ok(digits):
            return True
    return False


def mask_card_numbers(value: str, replacement: str = "[card number removed]") -> str:
    """Replace every card-number-like sequence (see contains_card_number)."""

    def repl(match: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", match.group())
        return replacement if 13 <= len(digits) <= 19 and _luhn_ok(digits) else match.group()

    return _DIGIT_RUN.sub(repl, value)


def _no_card_number(value: str | None) -> str | None:
    if value and contains_card_number(value):
        raise PydanticCustomError("card_number_not_allowed", "Card numbers must never be stored")
    return value


# Free text that staff could paste a card number into (notes, references).
SafeText = Annotated[str, AfterValidator(_no_card_number)]

Code = Annotated[
    str, StringConstraints(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9][A-Za-z0-9_\-\.]*$")
]
ShortStr = Annotated[str, StringConstraints(max_length=200)]
NonEmptyShortStr = Annotated[str, StringConstraints(min_length=1, max_length=200)]
Notes = Annotated[str, StringConstraints(max_length=5_000), AfterValidator(_no_card_number)]
Money = Annotated[Decimal, Field(max_digits=14, decimal_places=2, ge=0)]
CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
CountryCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class UpdateModel(InputModel):
    """PATCH payloads carry the version the client edited."""

    version: int = Field(ge=1)


class OutputModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class Pagination(BaseModel):
    limit: int = Field(50, ge=1, le=500)
    offset: int = Field(0, ge=0)
