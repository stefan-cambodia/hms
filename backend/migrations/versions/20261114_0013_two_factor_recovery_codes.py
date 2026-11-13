"""two-factor authentication: recovery codes, per-role requirement, no code replay

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-14 09:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "roles", sa.Column("require_2fa", sa.Boolean(), server_default=sa.text("false"), nullable=False)
    )
    op.add_column("users", sa.Column("totp_last_step", sa.BigInteger(), nullable=True))
    op.create_table(
        "user_recovery_codes",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_user_recovery_codes_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_recovery_codes")),
    )
    op.create_index(op.f("ix_user_recovery_codes_user_id"), "user_recovery_codes", ["user_id"])
    # Visible only with the user they belong to (that user's organisation).
    cond = "EXISTS (SELECT 1 FROM users p WHERE p.id = user_recovery_codes.user_id)"
    op.execute("ALTER TABLE user_recovery_codes ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant ON user_recovery_codes USING ({cond}) WITH CHECK ({cond})")


def downgrade() -> None:
    op.drop_table("user_recovery_codes")
    op.drop_column("users", "totp_last_step")
    op.drop_column("roles", "require_2fa")
