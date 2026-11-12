"""Idempotency-Key support for creation requests (reservations, payments,
charges): a retried request returns the result of the first attempt instead
of creating a duplicate."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import HotelContext
from app.core.errors import Conflict
from app.modules.reservations.models import IdempotencyKey


def digest(scope: str, payload: Any) -> str:
    """Hash of the request; the scope keeps one key from being replayed on another endpoint."""
    body = json.dumps({"scope": scope, "payload": payload}, sort_keys=True, default=str)
    return hashlib.sha256(body.encode()).hexdigest()


async def previous(db: AsyncSession, ctx: HotelContext, key: str, request_hash: str) -> uuid.UUID | None:
    row = await db.get(IdempotencyKey, (ctx.hotel_id, ctx.actor.user_id, key))
    if row is None:
        return None
    if row.request_hash != request_hash:
        raise Conflict("IDEMPOTENCY_KEY_REUSED", "This Idempotency-Key was used for a different request")
    return row.resource_id


async def claim(db: AsyncSession, ctx: HotelContext, key: str, request_hash: str) -> uuid.UUID | None:
    """Claim the key for this transaction. Returns the resource id created by an
    earlier attempt (the caller then replays it), or None once claimed.

    A concurrent retry blocks on the primary key until the first attempt
    commits, then fails the insert and replays the committed result."""
    found = await previous(db, ctx, key, request_hash)
    if found:
        return found
    db.add(
        IdempotencyKey(
            hotel_id=ctx.hotel_id,
            user_id=ctx.actor.user_id,
            key=key,
            request_hash=request_hash,
            resource_id=uuid.uuid4(),
        )
    )
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        found = await previous(db, ctx, key, request_hash)
        if found:
            return found
        raise
    return None


async def bind(db: AsyncSession, ctx: HotelContext, key: str, resource_id: uuid.UUID) -> None:
    row = await db.get(IdempotencyKey, (ctx.hotel_id, ctx.actor.user_id, key))
    assert row is not None
    row.resource_id = resource_id
