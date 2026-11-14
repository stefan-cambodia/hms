"""split folios: the company pays the room, the guest the extras

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-14 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_GUARD = "FOR EACH ROW EXECUTE FUNCTION hms_guard_financial_row({})"


def _charges_guard(mutable: str) -> None:
    op.execute("DROP TRIGGER trg_folio_charges_immutable ON folio_charges")
    args = ", ".join(f"'{c.strip()}'" for c in mutable.split(","))
    op.execute(
        f"CREATE TRIGGER trg_folio_charges_immutable BEFORE UPDATE OR DELETE ON folio_charges {_GUARD.format(args)}"
    )


def upgrade() -> None:
    # What the company pays when the reservation is billed to one: everything
    # (one folio) or the room only (two folios: company and guest).
    op.add_column(
        "reservations",
        sa.Column("company_pays", sa.String(length=10), server_default="all", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_reservations_company_pays"), "reservations", "company_pays IN ('all','room')"
    )

    # A charge can be moved to the other folio (who pays it is not an amount).
    op.add_column("folio_charges", sa.Column("folio", sa.String(length=10), nullable=True))
    op.create_check_constraint(
        op.f("ck_folio_charges_folio"), "folio_charges", "folio IS NULL OR folio IN ('guest','company')"
    )
    _charges_guard("is_void, void_reason, voided_at, voided_by, updated_at, folio")

    # A payment belongs to one folio for good; transfers settle the company's.
    op.add_column(
        "payments", sa.Column("folio", sa.String(length=10), server_default="guest", nullable=False)
    )
    op.execute("ALTER TABLE payments DISABLE TRIGGER trg_payments_immutable")
    op.execute("UPDATE payments SET folio = 'company' WHERE method = 'city_ledger'")
    op.execute("ALTER TABLE payments ENABLE TRIGGER trg_payments_immutable")
    op.create_check_constraint(
        op.f("ck_payments_folio"),
        "payments",
        "folio IN ('guest','company') AND (method <> 'city_ledger' OR folio = 'company')",
    )

    # One issued invoice per folio ('all' when the folio is not split).
    op.add_column("invoices", sa.Column("folio", sa.String(length=10), server_default="all", nullable=False))
    op.create_check_constraint(op.f("ck_invoices_folio"), "invoices", "folio IN ('all','guest','company')")
    op.drop_index("uq_invoices_one_issued_per_reservation", table_name="invoices")
    op.create_index(
        "uq_invoices_one_issued_per_folio",
        "invoices",
        ["reservation_id", "folio"],
        unique=True,
        postgresql_where=sa.text("status = 'issued'"),
    )


def downgrade() -> None:
    op.drop_index("uq_invoices_one_issued_per_folio", table_name="invoices")
    op.create_index(
        "uq_invoices_one_issued_per_reservation",
        "invoices",
        ["reservation_id"],
        unique=True,
        postgresql_where=sa.text("status = 'issued'"),
    )
    op.drop_constraint(op.f("ck_invoices_folio"), "invoices", type_="check")
    op.drop_column("invoices", "folio")
    op.drop_constraint(op.f("ck_payments_folio"), "payments", type_="check")
    op.drop_column("payments", "folio")
    _charges_guard("is_void, void_reason, voided_at, voided_by, updated_at")
    op.drop_constraint(op.f("ck_folio_charges_folio"), "folio_charges", type_="check")
    op.drop_column("folio_charges", "folio")
    op.drop_constraint(op.f("ck_reservations_company_pays"), "reservations", type_="check")
    op.drop_column("reservations", "company_pays")
