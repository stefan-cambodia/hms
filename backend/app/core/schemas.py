"""Shared Pydantic types used by every module's schemas."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Generic, Literal, TypeVar, get_args

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
)

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

Code = Annotated[
    str, StringConstraints(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9][A-Za-z0-9_\-\.]*$")
]
ShortStr = Annotated[str, StringConstraints(max_length=200)]
NonEmptyShortStr = Annotated[str, StringConstraints(min_length=1, max_length=200)]
Notes = Annotated[str, StringConstraints(max_length=5_000)]
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
