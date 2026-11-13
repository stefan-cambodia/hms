"""end-of-day closures (night audit)

Append-only: the API's role may insert and read closures, never change or
delete them; row-level security like every hotel table.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-13 15:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

IN_HOTELS = "hotel_id = ANY ((SELECT hms_hotels())::uuid[])"


def upgrade() -> None:
    op.create_table(
        "day_closures",
        sa.Column("hotel_id", sa.UUID(), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("closed_by", sa.UUID(), nullable=True),
        sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("open_items", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["hotel_id"], ["hotels.id"], name=op.f("fk_day_closures_hotel_id_hotels"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["closed_by"], ["users.id"], name=op.f("fk_day_closures_closed_by_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_day_closures")),
        sa.UniqueConstraint("hotel_id", "business_date", name=op.f("uq_day_closures_hotel_id_business_date")),
    )
    op.execute("ALTER TABLE day_closures ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant ON day_closures USING ({IN_HOTELS}) WITH CHECK ({IN_HOTELS})")
    # Default privileges (0010) granted everything to hms_app: closures are append-only.
    op.execute("REVOKE UPDATE, DELETE ON day_closures FROM hms_app")


def downgrade() -> None:
    op.drop_table("day_closures")
