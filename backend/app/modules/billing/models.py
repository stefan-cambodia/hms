"""Guest folio (extra charges), payments, invoices and accepted currencies.

Money rules:
* Amounts are Decimal, stored in the reservation's (hotel's) currency.
  A payment in a foreign currency also keeps the amount tendered, its
  currency and the exchange rate used.
* Charges, payments and invoices are never deleted: mistakes are voided with
  a reason. Database triggers keep amounts immutable once written.
* No card number, CVV or track data is ever stored: only brand and last 4.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, Timestamps, UUIDPk, Versioned

CHARGE_KINDS = ("service", "fee", "adjustment", "outlet")
FEE_TYPES = ("cancellation", "no_show", "early_departure", "late_checkout", "damage", "other")
PAYMENT_KINDS = ("payment", "deposit", "refund")
# city_ledger: the balance transferred to a company account (not money received).
PAYMENT_METHODS = ("cash", "card", "bank_transfer", "online", "other", "city_ledger")
CARD_BRANDS = ("visa", "mastercard", "amex", "unionpay", "jcb", "discover", "other")


class Currency(UUIDPk, Timestamps, Versioned, Base):
    """A foreign currency accepted for payments, with its current exchange rate
    expressed as units of this currency per 1 unit of the hotel currency
    (e.g. hotel in USD, KHR at 4100). Every payment stores the rate it used."""

    __tablename__ = "currencies"

    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(3))
    units_per_base: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))

    __table_args__ = (
        UniqueConstraint("hotel_id", "code"),
        CheckConstraint("units_per_base > 0", name="rate_positive"),
    )


class FolioCharge(UUIDPk, Timestamps, Base):
    """An extra charge on a reservation's folio (accommodation comes from the
    reservation's nightly prices). Service charges are taxed with the hotel's
    service taxes at posting time; fees and adjustments are final amounts."""

    __tablename__ = "folio_charges"

    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"))
    reservation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    reservation_room_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("reservation_rooms.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(20))
    fee_type: Mapped[str | None] = mapped_column(String(20))
    service_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # Service name in every language at posting time, so invoices in any
    # language stay correct even if the catalog is renamed later.
    name: Mapped[dict[str, str]] = mapped_column(JSONB, server_default=text("'{}'"))
    description: Mapped[str | None] = mapped_column(String(300))
    service_date: Mapped[date] = mapped_column(Date)
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default="0")
    tax_breakdown: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default=text("'[]'"))
    is_void: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    void_reason: Mapped[str | None] = mapped_column(String(500))
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    voided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    __table_args__ = (
        ForeignKeyConstraint(
            ["hotel_id", "reservation_id"],
            ["reservations.hotel_id", "reservations.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["hotel_id", "service_id"], ["services.hotel_id", "services.id"], ondelete="RESTRICT"
        ),
        CheckConstraint("kind IN ('service','fee','adjustment','outlet')", name="kind"),
        CheckConstraint(
            "fee_type IS NULL OR fee_type IN "
            "('cancellation','no_show','early_departure','late_checkout','damage','other')",
            name="fee_type",
        ),
        CheckConstraint("(kind = 'fee') = (fee_type IS NOT NULL)", name="fee_type_for_fees"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("kind = 'adjustment' OR (unit_price >= 0 AND amount >= 0)", name="amount_sign"),
        CheckConstraint("NOT is_void OR void_reason IS NOT NULL", name="void_reason"),
        Index("ix_folio_charges_reservation", "reservation_id"),
    )


class Payment(UUIDPk, Timestamps, Base):
    """Money received from (or refunded to) the guest. `amount` is what was
    tendered in `currency`; `amount_base` is its value in the hotel currency
    at `exchange_rate` (units of `currency` per 1 hotel-currency unit)."""

    __tablename__ = "payments"

    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"))
    reservation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    number: Mapped[str] = mapped_column(String(30))
    kind: Mapped[str] = mapped_column(String(20))
    method: Mapped[str] = mapped_column(String(20))
    amount: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    currency: Mapped[str] = mapped_column(String(3))
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(18, 6), server_default="1")
    amount_base: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    reference: Mapped[str | None] = mapped_column(String(100))
    card_brand: Mapped[str | None] = mapped_column(String(20))
    card_last4: Mapped[str | None] = mapped_column(String(4))
    notes: Mapped[str | None] = mapped_column(String(500))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    received_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    is_void: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    void_reason: Mapped[str | None] = mapped_column(String(500))
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    voided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # Transfers to a company account (method 'city_ledger'): the company, the
    # invoice made out to it, and when it is due.
    company_account_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("invoices.id", ondelete="RESTRICT"))
    due_date: Mapped[date | None] = mapped_column(Date)

    __table_args__ = (
        ForeignKeyConstraint(
            ["hotel_id", "reservation_id"],
            ["reservations.hotel_id", "reservations.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["hotel_id", "company_account_id"],
            ["company_accounts.hotel_id", "company_accounts.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("hotel_id", "number"),
        CheckConstraint("kind IN ('payment','deposit','refund')", name="kind"),
        CheckConstraint(
            "method IN ('cash','card','bank_transfer','online','other','city_ledger')", name="method"
        ),
        CheckConstraint(
            "(method = 'city_ledger') = (company_account_id IS NOT NULL) AND "
            "(method <> 'city_ledger' OR "
            "(kind = 'payment' AND invoice_id IS NOT NULL AND due_date IS NOT NULL))",
            name="city_ledger",
        ),
        CheckConstraint("amount > 0 AND amount_base > 0 AND exchange_rate > 0", name="amount_positive"),
        CheckConstraint("card_last4 IS NULL OR card_last4 ~ '^[0-9]{4}$'", name="card_last4"),
        CheckConstraint("NOT is_void OR void_reason IS NOT NULL", name="void_reason"),
        Index("ix_payments_reservation", "reservation_id"),
        Index("ix_payments_hotel_received", "hotel_id", "received_at"),
        Index(
            "ix_payments_company_account",
            "company_account_id",
            postgresql_where=text("company_account_id IS NOT NULL"),
        ),
    )


class Invoice(UUIDPk, Timestamps, Base):
    """An issued invoice: an immutable snapshot of the folio in one language,
    with a gapless number. It can only be voided (the number is never reused)."""

    __tablename__ = "invoices"

    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"))
    reservation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    number: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(10), server_default="issued")
    issue_date: Mapped[date] = mapped_column(Date)
    language: Mapped[str] = mapped_column(String(8))
    currency: Mapped[str] = mapped_column(String(3))
    bill_to: Mapped[dict[str, Any]] = mapped_column(JSONB)
    document: Mapped[dict[str, Any]] = mapped_column(JSONB)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    tax_total: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    paid_total: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    void_reason: Mapped[str | None] = mapped_column(String(500))
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    voided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    __table_args__ = (
        ForeignKeyConstraint(
            ["hotel_id", "reservation_id"],
            ["reservations.hotel_id", "reservations.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("hotel_id", "number"),
        CheckConstraint("status IN ('issued','void')", name="status"),
        CheckConstraint("status <> 'void' OR void_reason IS NOT NULL", name="void_reason"),
        Index(
            "uq_invoices_one_issued_per_reservation",
            "reservation_id",
            unique=True,
            postgresql_where=text("status = 'issued'"),
        ),
        Index("ix_invoices_hotel_issue_date", "hotel_id", "issue_date"),
    )
