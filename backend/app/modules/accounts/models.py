"""Company accounts (city ledger).

A company (travel agency, NGO, employer) that the hotel bills directly. When a
reservation is authorised for direct billing, its balance is *transferred* to
the company's account at departure: the invoice is made out to the company
and the folio is settled by a `city_ledger` settlement (billing.Payment with
method 'city_ledger'), which is not money received. The company later pays
the hotel (AccountPayment, money received) and the payment is allocated to
the open transfers, oldest first unless chosen otherwise.

    open amount of a transfer = transfer amount - allocations of live payments
    account balance           = live transfers - live payments (unallocated
                                money is a credit on the account)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, Timestamps, UUIDPk, Versioned

RECEIPT_METHODS = ("cash", "card", "bank_transfer", "online", "other")


class CompanyAccount(UUIDPk, Timestamps, Versioned, Base):
    __tablename__ = "company_accounts"

    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(200))
    legal_name: Mapped[str | None] = mapped_column(String(200))
    tax_id: Mapped[str | None] = mapped_column(String(50))
    address: Mapped[str | None] = mapped_column(String(300))
    city: Mapped[str | None] = mapped_column(String(100))
    country_code: Mapped[str | None] = mapped_column(String(2))
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(50))
    contact_name: Mapped[str | None] = mapped_column(String(200))
    language: Mapped[str | None] = mapped_column(String(8))  # of its invoices and statements
    payment_terms_days: Mapped[int] = mapped_column(Integer, server_default=text("30"))
    credit_limit: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("hotel_id", "code"),
        UniqueConstraint("hotel_id", "id"),  # target of composite foreign keys
        CheckConstraint("payment_terms_days BETWEEN 0 AND 365", name="terms"),
        CheckConstraint("credit_limit IS NULL OR credit_limit >= 0", name="credit_limit"),
    )


class AccountPayment(UUIDPk, Timestamps, Base):
    """Money received from a company. Append-only like every financial row:
    amounts never change, mistakes are voided with a reason."""

    __tablename__ = "account_payments"

    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"))
    company_account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    number: Mapped[str] = mapped_column(String(30))
    method: Mapped[str] = mapped_column(String(20))
    amount: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    currency: Mapped[str] = mapped_column(String(3))
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(18, 6), server_default="1")
    amount_base: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    reference: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(String(500))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    received_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    is_void: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    void_reason: Mapped[str | None] = mapped_column(String(500))
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    voided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    __table_args__ = (
        ForeignKeyConstraint(
            ["hotel_id", "company_account_id"],
            ["company_accounts.hotel_id", "company_accounts.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("hotel_id", "number"),
        CheckConstraint("method IN ('cash','card','bank_transfer','online','other')", name="method"),
        CheckConstraint("amount > 0 AND amount_base > 0 AND exchange_rate > 0", name="amount_positive"),
        CheckConstraint("NOT is_void OR void_reason IS NOT NULL", name="void_reason"),
        Index("ix_account_payments_account", "company_account_id"),
        Index("ix_account_payments_hotel_received", "hotel_id", "received_at"),
    )


class AccountAllocation(Base):
    """Part of a company payment applied to one transfer (open item)."""

    __tablename__ = "account_allocations"

    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"))
    account_payment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("account_payments.id", ondelete="RESTRICT")
    )
    transfer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payments.id", ondelete="RESTRICT"))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))

    __table_args__ = (
        PrimaryKeyConstraint("account_payment_id", "transfer_id"),
        CheckConstraint("amount > 0", name="amount_positive"),
        Index("ix_account_allocations_transfer", "transfer_id"),
    )
