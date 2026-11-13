"""photos and logos (media files stored in the database)

Each file belongs to the hotel (logo) or to exactly one room category,
facility or maintenance request, through real foreign keys; row-level
security like every hotel table.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-13 19:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

IN_HOTELS = "hotel_id = ANY ((SELECT hms_hotels())::uuid[])"


def upgrade() -> None:
    op.create_table(
        "media_files",
        sa.Column("hotel_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("room_type_id", sa.UUID(), nullable=True),
        sa.Column("facility_id", sa.UUID(), nullable=True),
        sa.Column("maintenance_request_id", sa.UUID(), nullable=True),
        sa.Column("filename", sa.String(length=200), nullable=False),
        sa.Column("content_type", sa.String(length=40), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("thumbnail", sa.LargeBinary(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("uploaded_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint("kind IN ('logo', 'photo')", name=op.f("ck_media_files_kind")),
        sa.CheckConstraint(
            "content_type IN ('image/jpeg', 'image/png')", name=op.f("ck_media_files_content_type")
        ),
        sa.CheckConstraint(
            "num_nonnulls(room_type_id, facility_id, maintenance_request_id)"
            " = CASE WHEN kind = 'logo' THEN 0 ELSE 1 END",
            name=op.f("ck_media_files_one_owner"),
        ),
        sa.CheckConstraint(
            "archived_at IS NULL OR kind = 'logo'", name=op.f("ck_media_files_archive_logos_only")
        ),
        sa.ForeignKeyConstraint(
            ["hotel_id"], ["hotels.id"], name=op.f("fk_media_files_hotel_id_hotels"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["room_type_id"],
            ["room_types.id"],
            name=op.f("fk_media_files_room_type_id_room_types"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["facility_id"],
            ["facilities.id"],
            name=op.f("fk_media_files_facility_id_facilities"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["maintenance_request_id"],
            ["maintenance_requests.id"],
            name=op.f("fk_media_files_maintenance_request_id_maintenance_requests"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"], ["users.id"], name=op.f("fk_media_files_uploaded_by_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_media_files")),
    )
    op.create_index(
        "uq_media_files_current_logo",
        "media_files",
        ["hotel_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'logo' AND archived_at IS NULL"),
    )
    for column in ("room_type_id", "facility_id", "maintenance_request_id"):
        op.create_index(
            f"ix_media_files_{column}",
            "media_files",
            [column],
            postgresql_where=sa.text(f"{column} IS NOT NULL"),
        )
    # Images are already compressed: do not spend CPU trying again (TOAST).
    op.execute("ALTER TABLE media_files ALTER COLUMN data SET STORAGE EXTERNAL")
    op.execute("ALTER TABLE media_files ALTER COLUMN thumbnail SET STORAGE EXTERNAL")
    op.execute("ALTER TABLE media_files ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant ON media_files USING ({IN_HOTELS}) WITH CHECK ({IN_HOTELS})")


def downgrade() -> None:
    op.drop_table("media_files")
