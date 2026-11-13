"""Photos and logos, stored in the database.

The bytes live in PostgreSQL (`bytea`, kept out of line by TOAST and never
loaded unless asked for), not on disk: the verified backups and the restore
from the Backups screen then cover them with everything else, and row-level
security isolates them like every other hotel table. Uploads are re-encoded
and scaled down (media/images.py), so a photo weighs a few hundred kB.

Each file belongs to exactly one owner through a real foreign key, so it
disappears with its room category, facility or maintenance request. A hotel
logo has no owner row; replacing or removing it archives the old file,
because issued invoices keep showing the logo they were issued with.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, LargeBinary, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.core.models import Base, UUIDPk

OWNER_COLUMNS = ("room_type_id", "facility_id", "maintenance_request_id")


class MediaFile(UUIDPk, Base):
    __tablename__ = "media_files"

    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(10))  # logo | photo
    room_type_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("room_types.id", ondelete="CASCADE"))
    facility_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("facilities.id", ondelete="CASCADE"))
    maintenance_request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("maintenance_requests.id", ondelete="CASCADE")
    )
    filename: Mapped[str] = mapped_column(String(200))
    content_type: Mapped[str] = mapped_column(String(40))
    size: Mapped[int] = mapped_column(Integer)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    data: Mapped[bytes] = deferred(mapped_column(LargeBinary))
    thumbnail: Mapped[bytes] = deferred(mapped_column(LargeBinary))
    sort_order: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("kind IN ('logo', 'photo')", name="kind"),
        CheckConstraint("content_type IN ('image/jpeg', 'image/png')", name="content_type"),
        CheckConstraint(
            "num_nonnulls(room_type_id, facility_id, maintenance_request_id)"
            " = CASE WHEN kind = 'logo' THEN 0 ELSE 1 END",
            name="one_owner",
        ),
        CheckConstraint("archived_at IS NULL OR kind = 'logo'", name="archive_logos_only"),
        Index(
            "uq_media_files_current_logo",
            "hotel_id",
            unique=True,
            postgresql_where=text("kind = 'logo' AND archived_at IS NULL"),
        ),
        Index(
            "ix_media_files_room_type_id", "room_type_id", postgresql_where=text("room_type_id IS NOT NULL")
        ),
        Index("ix_media_files_facility_id", "facility_id", postgresql_where=text("facility_id IS NOT NULL")),
        Index(
            "ix_media_files_maintenance_request_id",
            "maintenance_request_id",
            postgresql_where=text("maintenance_request_id IS NOT NULL"),
        ),
    )
