"""company accounts (city ledger): direct billing, transfers, payments from companies

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-14 15:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

IN_HOTELS = "hotel_id = ANY ((SELECT hms_hotels())::uuid[])"


def _tenant(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant ON {table} USING ({IN_HOTELS}) WITH CHECK ({IN_HOTELS})")


def upgrade() -> None:
    op.create_table(
        "company_accounts",
        sa.Column("hotel_id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("legal_name", sa.String(length=200), nullable=True),
        sa.Column("tax_id", sa.String(length=50), nullable=True),
        sa.Column("address", sa.String(length=300), nullable=True),
        sa.Column("city", sa.String(length=100), nullable=True),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("contact_name", sa.String(length=200), nullable=True),
        sa.Column("language", sa.String(length=8), nullable=True),
        sa.Column("payment_terms_days", sa.Integer(), server_default=sa.text("30"), nullable=False),
        sa.Column("credit_limit", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("payment_terms_days BETWEEN 0 AND 365", name=op.f("ck_company_accounts_terms")),
        sa.CheckConstraint(
            "credit_limit IS NULL OR credit_limit >= 0", name=op.f("ck_company_accounts_credit_limit")
        ),
        sa.ForeignKeyConstraint(
            ["hotel_id"], ["hotels.id"], name=op.f("fk_company_accounts_hotel_id_hotels"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_company_accounts")),
        sa.UniqueConstraint("hotel_id", "code", name=op.f("uq_company_accounts_hotel_id_code")),
        sa.UniqueConstraint("hotel_id", "id", name=op.f("uq_company_accounts_hotel_id_id")),
    )
    _tenant("company_accounts")

    op.create_table(
        "account_payments",
        sa.Column("hotel_id", sa.UUID(), nullable=False),
        sa.Column("company_account_id", sa.UUID(), nullable=False),
        sa.Column("number", sa.String(length=30), nullable=False),
        sa.Column("method", sa.String(length=20), nullable=False),
        sa.Column("amount", sa.Numeric(precision=16, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("exchange_rate", sa.Numeric(precision=18, scale=6), server_default="1", nullable=False),
        sa.Column("amount_base", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("reference", sa.String(length=100), nullable=True),
        sa.Column("notes", sa.String(length=500), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("received_by", sa.UUID(), nullable=True),
        sa.Column("is_void", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("void_reason", sa.String(length=500), nullable=True),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voided_by", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "method IN ('cash','card','bank_transfer','online','other')",
            name=op.f("ck_account_payments_method"),
        ),
        sa.CheckConstraint(
            "amount > 0 AND amount_base > 0 AND exchange_rate > 0",
            name=op.f("ck_account_payments_amount_positive"),
        ),
        sa.CheckConstraint(
            "NOT is_void OR void_reason IS NOT NULL", name=op.f("ck_account_payments_void_reason")
        ),
        sa.ForeignKeyConstraint(
            ["hotel_id"], ["hotels.id"], name=op.f("fk_account_payments_hotel_id_hotels"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["hotel_id", "company_account_id"],
            ["company_accounts.hotel_id", "company_accounts.id"],
            name=op.f("fk_account_payments_hotel_id_company_accounts"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_account_payments")),
        sa.UniqueConstraint("hotel_id", "number", name=op.f("uq_account_payments_hotel_id_number")),
    )
    op.create_index("ix_account_payments_account", "account_payments", ["company_account_id"])
    op.create_index("ix_account_payments_hotel_received", "account_payments", ["hotel_id", "received_at"])
    _tenant("account_payments")
    # Money received: never deleted, amounts never changed, a void is final.
    op.execute(
        "CREATE TRIGGER trg_account_payments_immutable BEFORE UPDATE OR DELETE ON account_payments "
        "FOR EACH ROW EXECUTE FUNCTION hms_guard_financial_row("
        "'is_void', 'void_reason', 'voided_at', 'voided_by', 'updated_at')"
    )
    op.execute("REVOKE DELETE ON account_payments FROM hms_app")

    # Transfers to a company: on the folio's payments (method city_ledger).
    op.add_column("payments", sa.Column("company_account_id", sa.UUID(), nullable=True))
    op.add_column("payments", sa.Column("invoice_id", sa.UUID(), nullable=True))
    op.add_column("payments", sa.Column("due_date", sa.Date(), nullable=True))
    op.create_foreign_key(
        op.f("fk_payments_hotel_id_company_accounts"),
        "payments",
        "company_accounts",
        ["hotel_id", "company_account_id"],
        ["hotel_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_payments_invoice_id_invoices"),
        "payments",
        "invoices",
        ["invoice_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(op.f("ck_payments_method"), "payments", type_="check")
    op.create_check_constraint(
        op.f("ck_payments_method"),
        "payments",
        "method IN ('cash','card','bank_transfer','online','other','city_ledger')",
    )
    op.create_check_constraint(
        op.f("ck_payments_city_ledger"),
        "payments",
        "(method = 'city_ledger') = (company_account_id IS NOT NULL) AND "
        "(method <> 'city_ledger' OR (kind = 'payment' AND invoice_id IS NOT NULL AND due_date IS NOT NULL))",
    )
    op.create_index(
        "ix_payments_company_account",
        "payments",
        ["company_account_id"],
        postgresql_where=sa.text("company_account_id IS NOT NULL"),
    )

    op.create_table(
        "account_allocations",
        sa.Column("hotel_id", sa.UUID(), nullable=False),
        sa.Column("account_payment_id", sa.UUID(), nullable=False),
        sa.Column("transfer_id", sa.UUID(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.CheckConstraint("amount > 0", name=op.f("ck_account_allocations_amount_positive")),
        sa.ForeignKeyConstraint(
            ["hotel_id"],
            ["hotels.id"],
            name=op.f("fk_account_allocations_hotel_id_hotels"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["account_payment_id"],
            ["account_payments.id"],
            name=op.f("fk_account_allocations_account_payment_id_account_payments"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["transfer_id"],
            ["payments.id"],
            name=op.f("fk_account_allocations_transfer_id_payments"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("account_payment_id", "transfer_id", name=op.f("pk_account_allocations")),
    )
    op.create_index("ix_account_allocations_transfer", "account_allocations", ["transfer_id"])
    _tenant("account_allocations")
    op.execute("REVOKE UPDATE, DELETE ON account_allocations FROM hms_app")

    op.add_column("reservations", sa.Column("company_account_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_reservations_hotel_id_company_accounts"),
        "reservations",
        "company_accounts",
        ["hotel_id", "company_account_id"],
        ["hotel_id", "id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_reservations_hotel_id_company_accounts"), "reservations", type_="foreignkey")
    op.drop_column("reservations", "company_account_id")
    op.drop_table("account_allocations")
    op.drop_index("ix_payments_company_account", table_name="payments")
    op.drop_constraint(op.f("ck_payments_city_ledger"), "payments", type_="check")
    op.drop_constraint(op.f("ck_payments_method"), "payments", type_="check")
    op.create_check_constraint(
        op.f("ck_payments_method"), "payments", "method IN ('cash','card','bank_transfer','online','other')"
    )
    op.drop_constraint(op.f("fk_payments_invoice_id_invoices"), "payments", type_="foreignkey")
    op.drop_constraint(op.f("fk_payments_hotel_id_company_accounts"), "payments", type_="foreignkey")
    op.drop_column("payments", "due_date")
    op.drop_column("payments", "invoice_id")
    op.drop_column("payments", "company_account_id")
    op.drop_table("account_payments")
    op.drop_table("company_accounts")
