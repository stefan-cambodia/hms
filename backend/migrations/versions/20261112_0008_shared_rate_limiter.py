"""shared rate limiter (login throttling across API processes)

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-12 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rate_limit_buckets",
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("bucket", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hits", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("key", "bucket", name=op.f("pk_rate_limit_buckets")),
        prefixes=["UNLOGGED"],
    )


def downgrade() -> None:
    op.drop_table("rate_limit_buckets")
