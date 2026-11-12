"""Transactional change events for real-time synchronisation.

`emit()` calls pg_notify inside the caller's transaction. PostgreSQL delivers
NOTIFY only when that transaction commits, so connected clients never hear
about changes that were rolled back. Payloads are deliberately small: clients
refetch through the normal, permission-checked REST API.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import Actor

CHANNEL = "hms_events"


async def emit(
    db: AsyncSession,
    *,
    hotel_id: uuid.UUID | None,
    entity: str,
    action: str,
    entity_id: Any = None,
    version: int | None = None,
    actor: Actor | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "hotel_id": str(hotel_id) if hotel_id else None,
        "entity": entity,
        "action": action,
        "id": str(entity_id) if entity_id is not None else None,
        "version": version,
        "actor": str(actor.user_id) if actor and actor.user_id else None,
    }
    if extra:
        payload["extra"] = extra
    await db.execute(
        text("SELECT pg_notify(:channel, :payload)"),
        {"channel": CHANNEL, "payload": json.dumps(payload, separators=(",", ":"))},
    )
