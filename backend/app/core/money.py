"""Decimal money helpers. Floats are never used for amounts."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from app.core.refdata import CURRENCY_MINOR_UNITS

ZERO = Decimal("0")


def quantum(currency: str) -> Decimal:
    return Decimal(1).scaleb(-CURRENCY_MINOR_UNITS.get(currency, 2))


def round_money(amount: Decimal, currency: str) -> Decimal:
    """Round half-up to the currency's minor unit, returned with 2 decimals for storage."""
    return amount.quantize(quantum(currency), rounding=ROUND_HALF_UP).quantize(Decimal("0.01"))
