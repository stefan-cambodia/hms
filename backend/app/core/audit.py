"""Append-only audit trail, written in the same transaction as the change."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy import BigInteger, DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.context import Actor
from app.core.models import Base

REDACTED = "***"
_SENSITIVE_FIELDS = {
    "password",
    "password_hash",
    "totp_secret",
    "credentials",
    "token_hash",
    "id_document_number",
}


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    hotel_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    source: Mapped[str] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(60))
    entity_type: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    changes: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ip: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        Index("ix_audit_logs_hotel_at", "hotel_id", "at"),
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
    )


def _jsonable(v: Any) -> Any:
    if isinstance(v, datetime | date | time):
        return v.isoformat()
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, Enum):
        return v.value
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, list | tuple | set | frozenset):
        return [_jsonable(x) for x in v]
    return v


def diff(before: dict[str, Any] | None, after: dict[str, Any] | None) -> dict[str, Any]:
    """{field: [old, new]} for changed fields, with secrets redacted."""
    before, after = before or {}, after or {}
    out: dict[str, Any] = {}
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key), after.get(key)
        if old != new:
            if key in _SENSITIVE_FIELDS:
                out[key] = [REDACTED if old is not None else None, REDACTED if new is not None else None]
            else:
                out[key] = [_jsonable(old), _jsonable(new)]
    return out


def record(
    db: AsyncSession,
    actor: Actor,
    action: str,
    entity_type: str,
    entity_id: Any = None,
    *,
    hotel_id: uuid.UUID | None = None,
    changes: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditLog(
            organization_id=actor.organization_id,
            hotel_id=hotel_id,
            user_id=actor.user_id,
            session_id=actor.session_id,
            source=actor.source,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            changes=_jsonable(changes) if changes else None,
            ip=actor.ip,
            request_id=actor.request_id,
        )
    )
