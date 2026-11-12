"""Shared persistence helpers for hotel-scoped aggregates.

They give every module the same guarantees: tenant scoping, optimistic locking,
an audit record and a real-time event in the same transaction as the change.
Business validation stays in each module's service.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from typing import Any, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit, events
from app.core.context import HotelContext
from app.core.errors import NotFound, VersionConflict

M = TypeVar("M")


async def get_scoped(
    db: AsyncSession,
    model: type[M],
    hotel_id: uuid.UUID,
    obj_id: uuid.UUID,
    *,
    code: str = "NOT_FOUND",
    for_update: bool = False,
) -> M:
    stmt = select(model).where(model.id == obj_id, model.hotel_id == hotel_id)  # type: ignore[attr-defined]
    if for_update:
        stmt = stmt.with_for_update()
    obj = (await db.scalars(stmt)).one_or_none()
    if obj is None:
        raise NotFound(code, f"{model.__name__} not found")
    return obj


async def paginate(db: AsyncSession, stmt: Select, *, limit: int, offset: int) -> tuple[Sequence[Any], int]:
    total = await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    items = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    return items, int(total or 0)


def check_version(obj: Any, version: int) -> None:
    if obj.version != version:
        raise VersionConflict(
            "VERSION_CONFLICT",
            "Record was modified by someone else",
            params={"current_version": obj.version},
        )


def snapshot(obj: Any, fields: Iterable[str]) -> dict[str, Any]:
    out = {}
    for f in fields:
        v = getattr(obj, f)
        if isinstance(v, list) and v and hasattr(v[0], "id"):
            v = sorted(str(x.id) for x in v)
        out[f] = v
    return out


async def create(db: AsyncSession, ctx: HotelContext, obj: Any, *, entity: str, fields: Iterable[str]) -> Any:
    db.add(obj)
    await db.flush()
    audit.record(
        db,
        ctx.actor,
        f"{entity}.create",
        entity,
        obj.id,
        hotel_id=ctx.hotel_id,
        changes=audit.diff(None, snapshot(obj, fields)),
    )
    await events.emit(
        db,
        hotel_id=ctx.hotel_id,
        entity=entity,
        action="created",
        entity_id=obj.id,
        version=getattr(obj, "version", None),
        actor=ctx.actor,
    )
    await db.commit()
    await db.refresh(obj)
    return obj


async def update(
    db: AsyncSession,
    ctx: HotelContext,
    obj: Any,
    changes: dict[str, Any],
    *,
    version: int,
    entity: str,
    fields: Iterable[str],
) -> Any:
    """Apply `changes` (already validated) if `version` matches."""
    check_version(obj, version)
    fields = list(fields)
    before = snapshot(obj, fields)
    for key, value in changes.items():
        setattr(obj, key, value)
    after = snapshot(obj, fields)
    delta = audit.diff(before, after)
    if not delta:
        return obj
    await db.flush()
    audit.record(db, ctx.actor, f"{entity}.update", entity, obj.id, hotel_id=ctx.hotel_id, changes=delta)
    await events.emit(
        db,
        hotel_id=ctx.hotel_id,
        entity=entity,
        action="updated",
        entity_id=obj.id,
        version=getattr(obj, "version", None),
        actor=ctx.actor,
    )
    await db.commit()
    await db.refresh(obj)
    return obj


async def delete(
    db: AsyncSession, ctx: HotelContext, obj: Any, *, entity: str, fields: Iterable[str]
) -> None:
    before = snapshot(obj, fields)
    obj_id = obj.id
    await db.delete(obj)
    await db.flush()  # FK RESTRICT violations surface here -> 409 IN_USE
    audit.record(
        db,
        ctx.actor,
        f"{entity}.delete",
        entity,
        obj_id,
        hotel_id=ctx.hotel_id,
        changes=audit.diff(before, None),
    )
    await events.emit(
        db, hotel_id=ctx.hotel_id, entity=entity, action="deleted", entity_id=obj_id, actor=ctx.actor
    )
    await db.commit()
