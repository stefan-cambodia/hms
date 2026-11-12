"""Declarative base and shared column mixins."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, MetaData, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

# Deterministic constraint names: error mapping (core.errors.register_constraint)
# and migrations both rely on them.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    # Fetch server-generated values (timestamps, defaults) with RETURNING so
    # attributes are never lazily refreshed (which async sessions cannot do).
    __mapper_args__ = {"eager_defaults": True}


class UUIDPk:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Versioned:
    """Optimistic locking. SQLAlchemy adds `WHERE version = :old` to every
    UPDATE and raises StaleDataError (-> 409 VERSION_CONFLICT) if a concurrent
    writer got there first. Services additionally compare the client-supplied
    version before applying a PATCH, so a stale form can never overwrite newer
    data."""

    version: Mapped[int] = mapped_column(Integer, nullable=False)

    @declared_attr.directive
    def __mapper_args__(cls) -> dict[str, Any]:
        return {"version_id_col": cls.__table__.c.version, "eager_defaults": True}  # type: ignore[attr-defined]


def to_dict(obj: Any, fields: list[str] | tuple[str, ...]) -> dict[str, Any]:
    """Snapshot selected attributes (used for audit diffs)."""
    return {f: getattr(obj, f) for f in fields}
