"""One synchronisation run for one connection: push the ARI delta, then pull,
import and acknowledge reservations.

Database work happens in short transactions; no transaction is held open
while waiting for the provider. Acknowledged values are recorded only after
the provider confirmed success, and the change queue is emptied only when
everything it covered was sent, so a failure never loses a change: the next
run recomputes current values and sends what is still different.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, func, select

from app.core import events
from app.core.db import sessionmaker
from app.core.security import decrypt_secret
from app.core.tenancy import tenant_scope
from app.modules.channels import ari, importer
from app.modules.channels.adapters import get_adapter
from app.modules.channels.adapters.base import (
    Capability,
    ChannelAdapter,
    ChannelError,
    ConfirmItem,
    ConnectionConfig,
    Exchange,
)
from app.modules.channels.models import (
    ChannelBooking,
    ChannelConnection,
    ChannelDirtyRange,
    ChannelInventoryState,
    ChannelMessage,
    ChannelRateState,
    ChannelSyncStatus,
)
from app.modules.hotels.models import Hotel
from app.modules.reservations.models import Reservation

logger = logging.getLogger("hms.channels")

# Seconds before retrying after consecutive failures (provider guidance:
# exponential backoff for transient errors, up to at least 30 minutes).
BACKOFF = (5, 15, 30, 60, 120, 300, 600, 1200, 1800)
MAX_DIRTY_PER_RUN = 5000


@dataclass
class SyncReport:
    inventory: int = 0
    restrictions: int = 0
    rates: int = 0
    pulled: int = 0
    imported: int = 0
    failed: int = 0
    error: str | None = None
    exchanges: list[Exchange] = field(default_factory=list)


def config_of(conn: ChannelConnection) -> ConnectionConfig:
    return ConnectionConfig(
        endpoint_url=conn.endpoint_url,
        environment=conn.environment,
        account_code=conn.account_code,
        username=conn.username,
        password=decrypt_secret(conn.password),
        hotel_code=conn.hotel_code,
        settings=dict(conn.settings or {}),
    )


async def save_exchanges(conn: ChannelConnection, exchanges: list[Exchange]) -> None:
    if not exchanges:
        return
    async with sessionmaker()() as db:
        db.add_all(
            ChannelMessage(
                connection_id=conn.id,
                hotel_id=conn.hotel_id,
                operation=e.operation,
                outcome=e.outcome,
                http_status=e.http_status,
                duration_ms=e.duration_ms,
                summary=e.summary,
                request_body=e.request_body,
                response_body=e.response_body,
            )
            for e in exchanges
        )
        await db.commit()
    exchanges.clear()


def is_due(
    conn: ChannelConnection, status: ChannelSyncStatus, today: date, has_dirty: bool, now: datetime
) -> bool:
    if not conn.enabled:
        return False
    push_due = conn.push_ari and (status.next_push_at is None or status.next_push_at <= now)
    horizon_end = today + timedelta(days=conn.horizon_days)
    push_work = has_dirty or status.full_refresh_requested or (status.horizon_end or date.min) < horizon_end
    pull_due = conn.pull_reservations and (status.next_pull_at is None or status.next_pull_at <= now)
    return bool((push_due and push_work) or pull_due)


async def _record_failure(conn_id: uuid.UUID, phase: str, exc: ChannelError, now: datetime) -> None:
    async with sessionmaker()() as db:
        status = await db.get(ChannelSyncStatus, conn_id, with_for_update=True)
        if status is None:
            return
        status.consecutive_failures += 1
        delay = BACKOFF[min(status.consecutive_failures - 1, len(BACKOFF) - 1)]
        if phase == "push":
            status.next_push_at = now + timedelta(seconds=delay)
        else:
            status.next_pull_at = now + timedelta(seconds=max(delay, 120))
        status.state = "degraded"
        status.last_error_at = now
        status.last_error = f"{phase} · {exc.kind}: {exc.message}"[:500]
        await events.emit(
            db, hotel_id=status.hotel_id, entity="channel_connection", action="sync", entity_id=conn_id
        )
        await db.commit()


async def _record_success(conn: ChannelConnection, phase: str, now: datetime, **values: object) -> None:
    async with sessionmaker()() as db:
        status = await db.get(ChannelSyncStatus, conn.id, with_for_update=True)
        if status is None:
            return
        status.consecutive_failures = 0
        status.state = "live" if conn.environment == "production" else "test_ok"
        if phase == "push":
            status.last_push_at = now
            status.next_push_at = None
        else:
            status.last_pull_at = now
            status.next_pull_at = now + timedelta(seconds=conn.pull_interval_seconds)
        for key, value in values.items():
            setattr(status, key, value)
        await events.emit(
            db, hotel_id=conn.hotel_id, entity="channel_connection", action="sync", entity_id=conn.id
        )
        await db.commit()


async def push(conn: ChannelConnection, adapter: ChannelAdapter, report: SyncReport, now: datetime) -> None:
    cfg = config_of(conn)
    async with sessionmaker()() as db:
        hotel = await db.get(Hotel, conn.hotel_id)
        status = await db.get(ChannelSyncStatus, conn.id)
        assert hotel is not None and status is not None
        today = hotel.today()
        horizon_end = today + timedelta(days=conn.horizon_days)
        full = status.full_refresh_requested
        if full:
            # Forget what the channel acknowledged: everything is sent again.
            await db.execute(
                delete(ChannelInventoryState).where(ChannelInventoryState.connection_id == conn.id)
            )
            await db.execute(delete(ChannelRateState).where(ChannelRateState.connection_id == conn.id))
            await db.commit()
        dirty = list(
            await db.scalars(
                select(ChannelDirtyRange)
                .where(ChannelDirtyRange.connection_id == conn.id)
                .order_by(ChannelDirtyRange.id)
                .limit(MAX_DIRTY_PER_RUN)
            )
        )
        ranges: dict[uuid.UUID | None, list[ari.Interval]] = {}
        for d in dirty:
            ranges.setdefault(d.room_type_id, []).append((d.start_date or today, d.end_date or horizon_end))
        covered = status.horizon_end
        if full or covered is None:
            ranges.setdefault(None, []).append((today, horizon_end))
        elif covered < horizon_end:
            ranges.setdefault(None, []).append((max(covered, today), horizon_end))
        plan = await ari.build_plan(db, conn, ranges, today=today, horizon_end=horizon_end)
        dirty_ids = [d.id for d in dirty]
        await db.rollback()

    log = report.exchanges.append
    if plan.inventory:
        await adapter.push_inventory(cfg, plan.inventory, log)
        report.inventory = len(plan.inventory)
        async with sessionmaker()() as db:
            await ari.record_inventory(db, plan.inventory_rows)
            await db.commit()
    if plan.restrictions:
        await adapter.push_restrictions(cfg, plan.restrictions, log)
        report.restrictions = len(plan.restrictions)
    if plan.rates:
        await adapter.push_rates(cfg, plan.rates, log)
        report.rates = len(plan.rates)
    async with sessionmaker()() as db:
        if plan.rate_rows:
            await ari.record_rates(db, plan.rate_rows)
        if dirty_ids:
            await db.execute(delete(ChannelDirtyRange).where(ChannelDirtyRange.id.in_(dirty_ids)))
        await db.commit()
    await _record_success(conn, "push", now, horizon_end=horizon_end, full_refresh_requested=False)


async def pull(conn: ChannelConnection, adapter: ChannelAdapter, report: SyncReport, now: datetime) -> None:
    cfg = config_of(conn)
    log = report.exchanges.append
    bookings = await adapter.pull_bookings(cfg, log)
    report.pulled = len(bookings)
    items: list[ConfirmItem] = []
    rows: list[uuid.UUID] = []
    for booking in bookings:
        async with sessionmaker()() as db:
            current = await db.get(ChannelConnection, conn.id)
            assert current is not None
            try:
                row = await importer.process(db, current, booking)
            except Exception:  # unexpected: leave it unconfirmed, the provider sends it again
                logger.exception("channel booking %s could not be processed", booking.external_id)
                await db.rollback()
                report.failed += 1
                continue
            code = await db.scalar(select(Reservation.code).where(Reservation.id == row.reservation_id))
            ok = row.import_status != "failed"
            report.imported += int(row.import_status == "imported")
            report.failed += int(not ok)
            items.append(
                ConfirmItem(
                    message_id=booking.message_id,
                    external_id=booking.external_id,
                    action=booking.action,
                    ok=ok,
                    pms_reference=code,
                    at=row.processed_at or now,
                    error_text=None if ok else f"{row.error_code}: {row.error_detail}",
                )
            )
            rows.append(row.id)
    if items:
        await adapter.confirm_bookings(cfg, items, log)
        async with sessionmaker()() as db:
            for row_id in rows:
                row = await db.get(ChannelBooking, row_id)
                if row is not None and row.confirmed_at is None:
                    row.confirmed_at = datetime.now(UTC)
            await db.commit()
    await _record_success(conn, "pull", now)


@dataclass(frozen=True)
class ConnectionRef:
    id: uuid.UUID
    hotel_id: uuid.UUID
    organization_id: uuid.UUID
    enabled: bool


async def connection_refs(connection_id: uuid.UUID | None = None) -> list[ConnectionRef]:
    """Connections and the tenant owning each. The worker serves every
    organisation, so this is its one cross-tenant lookup (a SECURITY DEFINER
    function returning identifiers only)."""
    async with sessionmaker()() as db:
        rows = (
            await db.execute(
                select(
                    func.hms_channel_connections(connection_id).table_valued(
                        "id", "hotel_id", "organization_id", "enabled"
                    )
                )
            )
        ).all()
    return [ConnectionRef(*row) for row in rows]


async def sync_connection(
    connection_id: uuid.UUID, *, push_only: bool = False, now: datetime | None = None
) -> SyncReport:
    refs = await connection_refs(connection_id)
    if not refs:
        return SyncReport()
    with tenant_scope(refs[0].organization_id, (refs[0].hotel_id,)):
        return await _sync_connection(connection_id, push_only=push_only, now=now)


async def _sync_connection(connection_id: uuid.UUID, *, push_only: bool, now: datetime | None) -> SyncReport:
    now = now or datetime.now(UTC)
    report = SyncReport()
    async with sessionmaker()() as db:
        conn = await db.get(ChannelConnection, connection_id)
        status = await db.get(ChannelSyncStatus, connection_id)
        if conn is None or status is None or not conn.enabled:
            return report
        hotel = await db.get(Hotel, conn.hotel_id)
        assert hotel is not None
        has_dirty = (
            await db.scalar(
                select(ChannelDirtyRange.id).where(ChannelDirtyRange.connection_id == conn.id).limit(1)
            )
            is not None
        )
        today = hotel.today()
        push_due = conn.push_ari and (status.next_push_at is None or status.next_push_at <= now)
        horizon_end = today + timedelta(days=conn.horizon_days)
        push_work = (
            has_dirty or status.full_refresh_requested or (status.horizon_end or date.min) < horizon_end
        )
        pull_due = (
            not push_only
            and conn.pull_reservations
            and (status.next_pull_at is None or status.next_pull_at <= now)
        )
    adapter = get_adapter(conn.provider)
    try:
        if push_due and push_work and Capability.ARI_PUSH in adapter.capabilities:
            try:
                await push(conn, adapter, report, now)
            except ChannelError as exc:
                report.error = exc.message
                await _record_failure(conn.id, "push", exc, now)
                return report
        if pull_due and Capability.RES_PULL in adapter.capabilities:
            try:
                await pull(conn, adapter, report, now)
            except ChannelError as exc:
                report.error = exc.message
                await _record_failure(conn.id, "pull", exc, now)
    finally:
        await save_exchanges(conn, report.exchanges)
    return report
