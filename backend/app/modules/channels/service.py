"""Channel manager: connections, mappings, actions and read models."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit, crud, events
from app.core.context import HotelContext
from app.core.errors import Conflict, NotFound, ValidationFailed, field_error
from app.core.security import encrypt_secret
from app.modules.channels import importer
from app.modules.channels.adapters import get_adapter
from app.modules.channels.adapters.base import (
    Capability,
    ChannelError,
    InboundBooking,
    InboundGuest,
    InboundNight,
    InboundStay,
)
from app.modules.channels.models import (
    ChannelBooking,
    ChannelConnection,
    ChannelDirtyRange,
    ChannelInventoryState,
    ChannelMessage,
    ChannelRateMap,
    ChannelRateState,
    ChannelRoomMap,
    ChannelSyncStatus,
)
from app.modules.channels.schemas import (
    BookingOut,
    ConnectionIn,
    ConnectionOut,
    ConnectionUpdate,
    MappingsIn,
    MappingsOut,
    ProductOut,
    RateMapIn,
    RoomMapIn,
    StatusOut,
    TestOut,
)
from app.modules.channels.sync import config_of, save_exchanges
from app.modules.pricing.models import RatePlan
from app.modules.reservations.models import Reservation
from app.modules.rooms.models import RoomType

FIELDS = (
    "provider",
    "name",
    "environment",
    "endpoint_url",
    "account_code",
    "username",
    "hotel_code",
    "enabled",
    "push_ari",
    "pull_reservations",
    "horizon_days",
    "pull_interval_seconds",
    "settings",
)
# Changing any of these points the connection at another account or hotel:
# what the old one acknowledged no longer says anything about the new one.
IDENTITY_FIELDS = ("environment", "endpoint_url", "account_code", "hotel_code", "provider")
FULL_REFRESH_INTERVAL = timedelta(hours=24)


async def _get(db: AsyncSession, ctx: HotelContext, connection_id: uuid.UUID) -> ChannelConnection:
    return await crud.get_scoped(
        db, ChannelConnection, ctx.hotel_id, connection_id, code="CONNECTION_NOT_FOUND"
    )


async def _status(db: AsyncSession, conn: ChannelConnection) -> ChannelSyncStatus:
    status = await db.get(ChannelSyncStatus, conn.id)
    assert status is not None
    return status


def mark_everything_dirty(
    db: AsyncSession, conn: ChannelConnection, room_type_id: uuid.UUID | None = None
) -> None:
    """Queue the whole horizon (same rule as the triggers: only while sending is on)."""
    if conn.push_ari:
        db.add(
            ChannelDirtyRange(
                connection_id=conn.id, room_type_id=room_type_id, start_date=None, end_date=None
            )
        )


async def _forget_acknowledged(db: AsyncSession, conn_id: uuid.UUID) -> None:
    await db.execute(delete(ChannelInventoryState).where(ChannelInventoryState.connection_id == conn_id))
    await db.execute(delete(ChannelRateState).where(ChannelRateState.connection_id == conn_id))


async def connection_out(db: AsyncSession, conn: ChannelConnection) -> ConnectionOut:
    status = await _status(db, conn)
    since = datetime.now(UTC) - timedelta(hours=24)
    pending = await db.scalar(
        select(func.count()).select_from(ChannelDirtyRange).where(ChannelDirtyRange.connection_id == conn.id)
    )
    mapped_types = set(
        await db.scalars(select(ChannelRoomMap.room_type_id).where(ChannelRoomMap.connection_id == conn.id))
    )
    active_types = set(
        await db.scalars(
            select(RoomType.id).where(RoomType.hotel_id == conn.hotel_id, RoomType.is_active.is_(True))
        )
    )
    rates = await db.scalar(
        select(func.count()).select_from(ChannelRateMap).where(ChannelRateMap.connection_id == conn.id)
    )
    attention = await db.scalar(
        select(func.count())
        .select_from(ChannelBooking)
        .where(
            ChannelBooking.connection_id == conn.id,
            (ChannelBooking.import_status.in_(("failed", "pending"))) | ChannelBooking.overbooked.is_(True),
        )
    )
    errors = await db.scalar(
        select(func.count())
        .select_from(ChannelMessage)
        .where(
            ChannelMessage.connection_id == conn.id,
            ChannelMessage.outcome == "error",
            ChannelMessage.at >= since,
        )
    )
    return ConnectionOut(
        **{f: getattr(conn, f) for f in (*FIELDS, "id", "version", "created_at")},
        status=StatusOut.model_validate(status),
        pending_changes=pending or 0,
        unmapped_room_types=len(active_types - mapped_types),
        mapped_rates=rates or 0,
        bookings_attention=attention or 0,
        errors_24h=errors or 0,
    )


async def list_connections(db: AsyncSession, ctx: HotelContext) -> list[ConnectionOut]:
    rows = await db.scalars(
        select(ChannelConnection)
        .where(ChannelConnection.hotel_id == ctx.hotel_id)
        .order_by(ChannelConnection.created_at)
    )
    return [await connection_out(db, c) for c in rows]


async def get_connection(db: AsyncSession, ctx: HotelContext, connection_id: uuid.UUID) -> ConnectionOut:
    return await connection_out(db, await _get(db, ctx, connection_id))


async def create_connection(db: AsyncSession, ctx: HotelContext, data: ConnectionIn) -> ConnectionOut:
    if data.environment == "production" and not data.endpoint_url:
        raise ValidationFailed("ENDPOINT_REQUIRED", fields=[field_error("endpoint_url", "ENDPOINT_REQUIRED")])
    values = data.model_dump(exclude={"password", "settings"})
    conn = ChannelConnection(
        id=uuid.uuid4(),
        hotel_id=ctx.hotel_id,
        password=encrypt_secret(data.password),
        settings=data.settings.model_dump(exclude_none=True),
        version=1,
        **values,
    )
    db.add(conn)
    await db.flush()
    db.add(ChannelSyncStatus(connection_id=conn.id, hotel_id=ctx.hotel_id, state="credentials_saved"))
    await crud.create(db, ctx, conn, entity="channel_connection", fields=FIELDS)
    return await get_connection(db, ctx, conn.id)


async def update_connection(
    db: AsyncSession, ctx: HotelContext, connection_id: uuid.UUID, data: ConnectionUpdate
) -> ConnectionOut:
    """Two steps: the versioned configuration (optimistic locking, audit),
    then the runtime consequences (state, what must be sent again)."""
    conn = await _get(db, ctx, connection_id)
    crud.check_version(conn, data.version)
    changes = data.model_dump(exclude_unset=True, exclude={"version", "password", "settings"})
    if data.settings is not None:
        changes["settings"] = data.settings.model_dump(exclude_none=True)
    changes = {k: v for k, v in changes.items() if v != getattr(conn, k)}
    environment = changes.get("environment", conn.environment)
    endpoint = changes.get("endpoint_url", conn.endpoint_url)
    if environment == "production" and not endpoint:
        raise ValidationFailed("ENDPOINT_REQUIRED", fields=[field_error("endpoint_url", "ENDPOINT_REQUIRED")])
    identity_changed = any(k in changes for k in IDENTITY_FIELDS)
    resume_push = bool(changes.get("push_ari")) and not conn.push_ari
    password_changed = data.password is not None

    # 1. Configuration. No query runs before crud.update, so nothing is
    # flushed (and versioned) before the version check.
    if password_changed:
        conn.password = encrypt_secret(data.password or "")
        audit.record(
            db,
            ctx.actor,
            "channel_connection.password_changed",
            "channel_connection",
            conn.id,
            hotel_id=ctx.hotel_id,
        )
    if changes:
        await crud.update(
            db, ctx, conn, changes, version=data.version, entity="channel_connection", fields=FIELDS
        )
    elif password_changed:
        await events.emit(
            db, hotel_id=ctx.hotel_id, entity="channel_connection", action="updated", entity_id=conn.id
        )
        await db.commit()

    # 2. Runtime consequences.
    status = await _status(db, conn)
    if password_changed or identity_changed:
        status.state = "credentials_saved"
    if identity_changed or resume_push:
        # What the old account acknowledged (or what was skipped while sending
        # was off) says nothing about the channel now: send the horizon again.
        await _forget_acknowledged(db, conn.id)
        mark_everything_dirty(db, conn)
        status.horizon_end = None
    if identity_changed:
        status.external_products = []
        status.products_fetched_at = None
    if "enabled" in changes:
        worked = status.last_push_at or status.last_pull_at
        resumed = (
            ("live" if conn.environment == "production" else "test_ok") if worked else "credentials_saved"
        )
        status.state = "paused" if not changes["enabled"] else resumed
        status.next_push_at = status.next_pull_at = None
    await db.commit()
    return await get_connection(db, ctx, conn.id)


async def delete_connection(db: AsyncSession, ctx: HotelContext, connection_id: uuid.UUID) -> None:
    conn = await _get(db, ctx, connection_id)
    await crud.delete(db, ctx, conn, entity="channel_connection", fields=FIELDS)


# --- actions calling the provider -----------------------------------------------


async def test_connection(db: AsyncSession, ctx: HotelContext, connection_id: uuid.UUID) -> TestOut:
    conn = await _get(db, ctx, connection_id)
    adapter = get_adapter(conn.provider)
    exchanges: list[Any] = []
    result = await adapter.test_connection(config_of(conn), exchanges.append)
    await save_exchanges(conn, exchanges)
    status = await _status(db, conn)
    await db.refresh(status)
    status.last_test_at = datetime.now(UTC)
    status.last_test_ok = result.ok
    status.last_test_message = result.message[:500]
    if result.ok and status.state in ("credentials_saved", "degraded") and status.consecutive_failures == 0:
        status.state = "live" if conn.environment == "production" else "test_ok"
    audit.record(
        db,
        ctx.actor,
        "channel_connection.test",
        "channel_connection",
        conn.id,
        hotel_id=ctx.hotel_id,
        changes={"ok": result.ok, "message": result.message[:200]},
    )
    await events.emit(
        db, hotel_id=ctx.hotel_id, entity="channel_connection", action="updated", entity_id=conn.id
    )
    await db.commit()
    return TestOut(ok=result.ok, message=result.message, state=status.state)


async def fetch_products(db: AsyncSession, ctx: HotelContext, connection_id: uuid.UUID) -> list[ProductOut]:
    conn = await _get(db, ctx, connection_id)
    adapter = get_adapter(conn.provider)
    if Capability.MAPPING_FETCH not in adapter.capabilities:
        raise Conflict("NOT_SUPPORTED")
    exchanges: list[Any] = []
    try:
        products = await adapter.fetch_mapping(config_of(conn), exchanges.append)
    except ChannelError as exc:
        await save_exchanges(conn, exchanges)
        raise Conflict(
            "PROVIDER_ERROR", exc.message, params={"kind": exc.kind, "message": exc.message}
        ) from exc
    await save_exchanges(conn, exchanges)
    status = await _status(db, conn)
    await db.refresh(status)
    out = [ProductOut.model_validate(p, from_attributes=True) for p in products]
    status.external_products = [p.model_dump() for p in out]
    status.products_fetched_at = datetime.now(UTC)
    await events.emit(
        db, hotel_id=ctx.hotel_id, entity="channel_connection", action="updated", entity_id=conn.id
    )
    await db.commit()
    return out


async def request_sync(db: AsyncSession, ctx: HotelContext, connection_id: uuid.UUID) -> None:
    """Run as soon as possible (clears any retry delay)."""
    conn = await _get(db, ctx, connection_id)
    if not conn.enabled:
        raise Conflict("CONNECTION_PAUSED")
    status = await _status(db, conn)
    status.next_push_at = None
    status.next_pull_at = None
    audit.record(
        db, ctx.actor, "channel_connection.sync_now", "channel_connection", conn.id, hotel_id=ctx.hotel_id
    )
    await db.commit()


async def request_full_refresh(db: AsyncSession, ctx: HotelContext, connection_id: uuid.UUID) -> None:
    conn = await _get(db, ctx, connection_id)
    status = await _status(db, conn)
    now = datetime.now(UTC)
    if status.last_full_refresh_at and now - status.last_full_refresh_at < FULL_REFRESH_INTERVAL:
        raise Conflict(
            "FULL_REFRESH_TOO_SOON",
            params={"next": (status.last_full_refresh_at + FULL_REFRESH_INTERVAL).isoformat()},
        )
    status.full_refresh_requested = True
    status.last_full_refresh_at = now
    status.next_push_at = None
    audit.record(
        db, ctx.actor, "channel_connection.full_refresh", "channel_connection", conn.id, hotel_id=ctx.hotel_id
    )
    await db.commit()


# --- mappings ------------------------------------------------------------------------


async def get_mappings(db: AsyncSession, ctx: HotelContext, connection_id: uuid.UUID) -> MappingsOut:
    conn = await _get(db, ctx, connection_id)
    status = await _status(db, conn)
    rooms = [
        RoomMapIn(room_type_id=m.room_type_id, external_code=m.external_code)
        for m in await db.scalars(select(ChannelRoomMap).where(ChannelRoomMap.connection_id == conn.id))
    ]
    rates = [
        RateMapIn(room_type_id=m.room_type_id, rate_plan_id=m.rate_plan_id, external_code=m.external_code)
        for m in await db.scalars(select(ChannelRateMap).where(ChannelRateMap.connection_id == conn.id))
    ]
    products = [ProductOut(**p) for p in status.external_products or []]
    unknown: list[str] = []
    if products:
        known_rooms = {p.room_code for p in products}
        room_codes = {r.room_type_id: r.external_code for r in rooms}
        known_pairs = {(p.room_code, p.rate_code) for p in products}
        unknown += [r.external_code for r in rooms if r.external_code not in known_rooms]
        unknown += [
            f"{room_codes.get(r.room_type_id, '?')}/{r.external_code}"
            for r in rates
            if (room_codes.get(r.room_type_id), r.external_code) not in known_pairs
        ]
    return MappingsOut(
        rooms=rooms,
        rates=rates,
        products=products,
        products_fetched_at=status.products_fetched_at,
        unknown_codes=unknown,
    )


async def replace_mappings(
    db: AsyncSession, ctx: HotelContext, connection_id: uuid.UUID, data: MappingsIn
) -> MappingsOut:
    conn = await _get(db, ctx, connection_id)
    types = {t.id: t for t in await db.scalars(select(RoomType).where(RoomType.hotel_id == ctx.hotel_id))}
    plans = {p.id: p for p in await db.scalars(select(RatePlan).where(RatePlan.hotel_id == ctx.hotel_id))}
    room_codes: dict[uuid.UUID, str] = {}
    for i, r in enumerate(data.rooms):
        if r.room_type_id not in types:
            raise ValidationFailed(
                "ROOM_TYPE_NOT_FOUND", fields=[field_error(f"rooms.{i}", "ROOM_TYPE_NOT_FOUND")]
            )
        if r.room_type_id in room_codes:
            raise ValidationFailed(
                "DUPLICATE_MAPPING", fields=[field_error(f"rooms.{i}", "DUPLICATE_MAPPING")]
            )
        if r.external_code in room_codes.values():
            raise ValidationFailed("DUPLICATE_CODE", fields=[field_error(f"rooms.{i}", "DUPLICATE_CODE")])
        room_codes[r.room_type_id] = r.external_code
    seen: set[tuple[uuid.UUID, uuid.UUID]] = set()
    seen_codes: set[tuple[uuid.UUID, str]] = set()
    for i, r in enumerate(data.rates):
        plan = plans.get(r.rate_plan_id)
        loc = f"rates.{i}"
        if r.room_type_id not in room_codes:
            raise ValidationFailed("ROOM_NOT_MAPPED", fields=[field_error(loc, "ROOM_NOT_MAPPED")])
        if plan is None:
            raise ValidationFailed("RATE_PLAN_NOT_FOUND", fields=[field_error(loc, "RATE_PLAN_NOT_FOUND")])
        if plan.room_type_ids and r.room_type_id not in plan.room_type_ids:
            raise ValidationFailed(
                "RATE_PLAN_NOT_FOR_ROOM_TYPE", fields=[field_error(loc, "RATE_PLAN_NOT_FOR_ROOM_TYPE")]
            )
        if (r.room_type_id, r.rate_plan_id) in seen or (r.room_type_id, r.external_code) in seen_codes:
            raise ValidationFailed("DUPLICATE_MAPPING", fields=[field_error(loc, "DUPLICATE_MAPPING")])
        seen.add((r.room_type_id, r.rate_plan_id))
        seen_codes.add((r.room_type_id, r.external_code))

    old_rooms = {
        m.room_type_id: m.external_code
        for m in await db.scalars(select(ChannelRoomMap).where(ChannelRoomMap.connection_id == conn.id))
    }
    old_rates = {
        (m.room_type_id, m.rate_plan_id): m.external_code
        for m in await db.scalars(select(ChannelRateMap).where(ChannelRateMap.connection_id == conn.id))
    }
    new_rates = {(r.room_type_id, r.rate_plan_id): r.external_code for r in data.rates}
    await db.execute(delete(ChannelRateMap).where(ChannelRateMap.connection_id == conn.id))
    await db.execute(delete(ChannelRoomMap).where(ChannelRoomMap.connection_id == conn.id))
    await db.flush()
    for rt_id, code in room_codes.items():
        db.add(
            ChannelRoomMap(
                connection_id=conn.id, hotel_id=ctx.hotel_id, room_type_id=rt_id, external_code=code
            )
        )
    for r in data.rates:
        db.add(
            ChannelRateMap(
                connection_id=conn.id,
                hotel_id=ctx.hotel_id,
                room_type_id=r.room_type_id,
                rate_plan_id=r.rate_plan_id,
                external_code=r.external_code,
            )
        )
    # A newly mapped or re-coded product starts from scratch: send everything for it.
    for rt_id, code in room_codes.items():
        if old_rooms.get(rt_id) != code:
            await db.execute(
                delete(ChannelInventoryState).where(
                    ChannelInventoryState.connection_id == conn.id,
                    ChannelInventoryState.room_type_id == rt_id,
                )
            )
            await db.execute(
                delete(ChannelRateState).where(
                    ChannelRateState.connection_id == conn.id, ChannelRateState.room_type_id == rt_id
                )
            )
            mark_everything_dirty(db, conn, rt_id)
    for key, code in new_rates.items():
        if old_rates.get(key) != code and old_rooms.get(key[0]) == room_codes.get(key[0]):
            await db.execute(
                delete(ChannelRateState).where(
                    ChannelRateState.connection_id == conn.id,
                    ChannelRateState.room_type_id == key[0],
                    ChannelRateState.rate_plan_id == key[1],
                )
            )
            mark_everything_dirty(db, conn, key[0])
    audit.record(
        db,
        ctx.actor,
        "channel_connection.mapping",
        "channel_connection",
        conn.id,
        hotel_id=ctx.hotel_id,
        changes={
            "rooms": [{str(k): v} for k, v in room_codes.items()],
            "rates": [{f"{k[0]}/{k[1]}": v} for k, v in new_rates.items()],
        },
    )
    await events.emit(
        db, hotel_id=ctx.hotel_id, entity="channel_connection", action="updated", entity_id=conn.id
    )
    await db.commit()
    return await get_mappings(db, ctx, conn.id)


# --- log and bookings ----------------------------------------------------------------


async def list_messages(
    db: AsyncSession, ctx: HotelContext, connection_id: uuid.UUID, *, errors_only: bool, limit: int
) -> list[ChannelMessage]:
    conn = await _get(db, ctx, connection_id)
    stmt = select(ChannelMessage).where(ChannelMessage.connection_id == conn.id)
    if errors_only:
        stmt = stmt.where(ChannelMessage.outcome == "error")
    return list(
        await db.scalars(stmt.order_by(ChannelMessage.at.desc(), ChannelMessage.id.desc()).limit(limit))
    )


async def get_message(db: AsyncSession, ctx: HotelContext, message_id: int) -> ChannelMessage:
    msg = await db.get(ChannelMessage, message_id)
    if msg is None or msg.hotel_id != ctx.hotel_id:
        raise NotFound("MESSAGE_NOT_FOUND")
    return msg


def _booking_out(b: ChannelBooking, conn_name: str, code: str | None) -> BookingOut:
    data = b.data or {}
    booker = data.get("booker") or {}
    stays = data.get("stays") or []
    return BookingOut(
        id=b.id,
        connection_id=b.connection_id,
        connection_name=conn_name,
        external_id=b.external_id,
        revision=b.revision,
        action=b.action,
        channel_name=b.channel_name,
        message_at=b.message_at,
        received_at=b.received_at,
        import_status=b.import_status,
        error_code=b.error_code,
        error_detail=b.error_detail,
        reservation_id=b.reservation_id,
        reservation_code=code,
        overbooked=b.overbooked,
        attempts=b.attempts,
        confirmed_at=b.confirmed_at,
        card_brand=b.card_brand,
        card_last4=b.card_last4,
        guest_name=" ".join(x for x in (booker.get("first_name"), booker.get("last_name")) if x and x != "-")
        or None,
        arrival=date.fromisoformat(min(s["arrival"] for s in stays)) if stays else None,
        departure=date.fromisoformat(max(s["departure"] for s in stays)) if stays else None,
        total=data.get("total"),
        currency=data.get("currency"),
    )


async def list_bookings(
    db: AsyncSession, ctx: HotelContext, *, status: str | None, attention: bool, limit: int
) -> list[BookingOut]:
    stmt = (
        select(ChannelBooking, ChannelConnection.name, Reservation.code)
        .join(ChannelConnection, ChannelConnection.id == ChannelBooking.connection_id)
        .outerjoin(Reservation, Reservation.id == ChannelBooking.reservation_id)
        .where(ChannelBooking.hotel_id == ctx.hotel_id)
    )
    if status:
        stmt = stmt.where(ChannelBooking.import_status == status)
    if attention:
        stmt = stmt.where(
            ChannelBooking.import_status.in_(("failed", "pending")) | ChannelBooking.overbooked.is_(True)
        )
    rows = await db.execute(stmt.order_by(ChannelBooking.received_at.desc()).limit(limit))
    return [_booking_out(b, name, code) for b, name, code in rows]


def booking_from_data(data: dict[str, Any]) -> InboundBooking:
    """Rebuild a stored booking (for a retry after the mapping was fixed)."""

    def d(v: str | None) -> date | None:
        return date.fromisoformat(v) if v else None

    stays = [
        InboundStay(
            room_code=s.get("room_code"),
            rate_code=s.get("rate_code"),
            arrival=date.fromisoformat(s["arrival"]),
            departure=date.fromisoformat(s["departure"]),
            adults=int(s.get("adults") or 1),
            children=int(s.get("children") or 0),
            nights=[
                InboundNight(date.fromisoformat(n["night"]), Decimal(n["amount"]), n.get("rate_code"))
                for n in s.get("nights") or []
            ],
            total=Decimal(s["total"]) if s.get("total") is not None else None,
            comments=list(s.get("comments") or []),
        )
        for s in data.get("stays") or []
    ]
    booker = data.get("booker")
    return InboundBooking(
        external_id=data["external_id"],
        message_id=data["message_id"],
        action=data["action"],
        message_at=datetime.fromisoformat(data["message_at"]) if data.get("message_at") else None,
        hotel_code=data.get("hotel_code"),
        channel_code=data.get("channel_code"),
        channel_name=data.get("channel_name"),
        channel_reference=data.get("channel_reference"),
        currency=data.get("currency"),
        amounts_after_tax=bool(data.get("amounts_after_tax", True)),
        total=Decimal(data["total"]) if data.get("total") is not None else None,
        stays=stays,
        booker=InboundGuest(**booker) if booker else None,
        comments=list(data.get("comments") or []),
        extra=dict(data.get("extra") or {}),
    )


async def retry_booking(db: AsyncSession, ctx: HotelContext, booking_id: uuid.UUID) -> BookingOut:
    """Import a failed booking again (for example after fixing the mapping).
    The provider was already told about the failure; this only fixes the PMS."""
    row = await crud.get_scoped(db, ChannelBooking, ctx.hotel_id, booking_id, code="BOOKING_NOT_FOUND")
    if row.import_status not in ("failed", "pending"):
        raise Conflict("BOOKING_ALREADY_PROCESSED", params={"status": row.import_status})
    conn = await db.get(ChannelConnection, row.connection_id)
    assert conn is not None
    booking = booking_from_data(row.data)
    booking.card_brand, booking.card_last4 = row.card_brand, row.card_last4
    row.import_status, row.error_code, row.error_detail = "pending", None, None
    await db.flush()
    audit.record(db, ctx.actor, "channel_booking.retry", "channel_booking", row.id, hotel_id=ctx.hotel_id)
    await db.commit()
    result = await importer.process(db, conn, booking)
    code = await db.scalar(select(Reservation.code).where(Reservation.id == result.reservation_id))
    return _booking_out(result, conn.name, code)


async def dismiss_booking(
    db: AsyncSession, ctx: HotelContext, booking_id: uuid.UUID, reason: str
) -> BookingOut:
    """Staff handled it by hand (for example entered or cancelled the reservation)."""
    row = await crud.get_scoped(db, ChannelBooking, ctx.hotel_id, booking_id, code="BOOKING_NOT_FOUND")
    if row.import_status not in ("failed", "pending") and not row.overbooked:
        raise Conflict("BOOKING_ALREADY_PROCESSED", params={"status": row.import_status})
    if row.import_status in ("failed", "pending"):
        row.import_status = "ignored"
    row.overbooked = False
    row.error_detail = f"Handled manually: {reason}"[:500]
    audit.record(
        db,
        ctx.actor,
        "channel_booking.dismiss",
        "channel_booking",
        row.id,
        hotel_id=ctx.hotel_id,
        changes={"reason": reason},
    )
    await events.emit(db, hotel_id=ctx.hotel_id, entity="channel_booking", action="updated", entity_id=row.id)
    await db.commit()
    conn = await db.get(ChannelConnection, row.connection_id)
    code = await db.scalar(select(Reservation.code).where(Reservation.id == row.reservation_id))
    return _booking_out(row, conn.name if conn else "", code)
