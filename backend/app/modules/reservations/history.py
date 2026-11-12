"""Reservation history: every change writes a staff-visible reservation event,
an audit record and a real-time notification, in the caller's transaction."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit, events
from app.core.context import HotelContext
from app.modules.reservations.models import Reservation, ReservationEvent


def event(db: AsyncSession, ctx: HotelContext, res: Reservation, action: str, **details: Any) -> None:
    db.add(
        ReservationEvent(
            hotel_id=ctx.hotel_id,
            reservation_id=res.id,
            user_id=ctx.actor.user_id,
            source=ctx.actor.source,
            action=action,
            details=audit._jsonable(details),
        )
    )


async def publish(db: AsyncSession, ctx: HotelContext, res: Reservation, action: str, changes: dict) -> None:
    audit.record(
        db, ctx.actor, f"reservation.{action}", "reservation", res.id, hotel_id=ctx.hotel_id, changes=changes
    )
    await events.emit(
        db,
        hotel_id=ctx.hotel_id,
        entity="reservation",
        action=action,
        entity_id=res.id,
        version=res.version,
        actor=ctx.actor,
    )
