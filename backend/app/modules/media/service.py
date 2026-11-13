"""Photos and logos: who may see and change them, and the stored files.

The API names an owner as (owner_type, owner_id):

* `hotel`: the hotel's logo (one current logo; owner_id is the hotel);
* `room_type`, `facility`: photos of a room category or a facility;
* `maintenance_request`: photos of a reported problem.

Image decoding is CPU-heavy, so it runs in a worker thread, two at a time
per API process, before any database lock is taken.
"""

from __future__ import annotations

import asyncio
import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit, events
from app.core.context import HotelContext
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.permissions import P
from app.modules.auth.models import User
from app.modules.facilities.models import Facility
from app.modules.hotels.models import Hotel
from app.modules.maintenance.models import MaintenanceRequest
from app.modules.media import images
from app.modules.media.models import MediaFile
from app.modules.rooms.models import RoomType

OwnerType = Literal["hotel", "room_type", "facility", "maintenance_request"]


@dataclass(frozen=True, slots=True)
class Rule:
    view: P
    edit: P
    limit: int
    column: str | None  # MediaFile column holding the owner id (None: the hotel logo)
    model: Any
    entity: str  # real-time event entity (its permission filters who hears it)


RULES: dict[str, Rule] = {
    "hotel": Rule(P.HOTEL_VIEW, P.CONFIG_HOTEL, 1, None, Hotel, "media"),
    "room_type": Rule(P.HOTEL_VIEW, P.CONFIG_ROOMS, 20, "room_type_id", RoomType, "media"),
    "facility": Rule(P.HOTEL_VIEW, P.CONFIG_FACILITIES, 20, "facility_id", Facility, "media"),
    "maintenance_request": Rule(
        P.MAINTENANCE_VIEW,
        P.MAINTENANCE_REPORT,
        10,
        "maintenance_request_id",
        MaintenanceRequest,
        "maintenance_request",
    ),
}

# Per API process: at most two images decoded at once (a 48 MP photo needs
# a few hundred MB while it is being scaled down).
_decoding = asyncio.Semaphore(2)


def _require(ctx: HotelContext, permission: P) -> None:
    if not ctx.has(permission):
        raise Forbidden("PERMISSION_DENIED", params={"permission": permission})


def owner_type_of(m: MediaFile) -> str:
    if m.room_type_id:
        return "room_type"
    if m.facility_id:
        return "facility"
    if m.maintenance_request_id:
        return "maintenance_request"
    return "hotel"


def owner_id_of(m: MediaFile) -> uuid.UUID:
    return m.room_type_id or m.facility_id or m.maintenance_request_id or m.hotel_id


def _owner_filter(ctx: HotelContext, owner_type: str, owner_id: uuid.UUID | None) -> list[Any]:
    rule = RULES[owner_type]
    conditions: list[Any] = [MediaFile.hotel_id == ctx.hotel_id]
    if rule.column is None:
        return [*conditions, MediaFile.kind == "logo", MediaFile.archived_at.is_(None)]
    if owner_id is None:
        raise ValidationFailed("MEDIA_OWNER_REQUIRED")
    return [*conditions, getattr(MediaFile, rule.column) == owner_id]


def clean_filename(name: str | None, content_type: str) -> str:
    """A display name for the file: no path, no control characters, the right extension."""
    base = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    base = "".join(ch for ch in unicodedata.normalize("NFC", base) if unicodedata.category(ch)[0] != "C")
    stem = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", base).strip(" .") or "image"
    ext = ".png" if content_type == "image/png" else ".jpg"
    return stem[:180] + ext


# --- reading -------------------------------------------------------------------------


async def media_out(db: AsyncSession, ctx: HotelContext, files: list[MediaFile]) -> list[dict[str, Any]]:
    users = {m.uploaded_by for m in files if m.uploaded_by}
    names: dict[uuid.UUID, str] = {}
    if users:
        rows = await db.execute(select(User.id, User.full_name).where(User.id.in_(users)))
        names = {user_id: name for user_id, name in rows}
    base = f"/api/v1/hotels/{ctx.hotel_id}/media"
    return [
        {
            "id": m.id,
            "owner_type": owner_type_of(m),
            "owner_id": owner_id_of(m),
            "kind": m.kind,
            "filename": m.filename,
            "content_type": m.content_type,
            "size": m.size,
            "width": m.width,
            "height": m.height,
            "sort_order": m.sort_order,
            "uploaded_by": m.uploaded_by,
            "uploaded_by_name": names.get(m.uploaded_by) if m.uploaded_by else None,
            "created_at": m.created_at,
            "url": f"{base}/{m.id}/content",
            "thumbnail_url": f"{base}/{m.id}/content?variant=thumbnail",
        }
        for m in files
    ]


async def list_media(
    db: AsyncSession, ctx: HotelContext, owner_type: str, owner_id: uuid.UUID | None
) -> list[MediaFile]:
    _require(ctx, RULES[owner_type].view)
    return list(
        await db.scalars(
            select(MediaFile)
            .where(*_owner_filter(ctx, owner_type, owner_id))
            .order_by(MediaFile.sort_order, MediaFile.created_at)
        )
    )


async def _get(db: AsyncSession, ctx: HotelContext, media_id: uuid.UUID) -> MediaFile:
    m = (
        await db.scalars(
            select(MediaFile).where(
                MediaFile.id == media_id, MediaFile.hotel_id == ctx.hotel_id, MediaFile.archived_at.is_(None)
            )
        )
    ).one_or_none()
    if m is None:
        raise NotFound("MEDIA_NOT_FOUND")
    return m


async def content(
    db: AsyncSession, ctx: HotelContext, media_id: uuid.UUID, variant: str
) -> tuple[MediaFile, bytes]:
    m = await _get(db, ctx, media_id)
    _require(ctx, RULES[owner_type_of(m)].view)
    column = MediaFile.thumbnail if variant == "thumbnail" else MediaFile.data
    return m, await db.scalar(select(column).where(MediaFile.id == m.id))


# --- changing ------------------------------------------------------------------------


async def _lock_owner(db: AsyncSession, ctx: HotelContext, owner_type: str, owner_id: uuid.UUID) -> Any:
    """The owner row, locked so that concurrent uploads count photos one at a time.
    FOR NO KEY UPDATE: rows referencing the owner can still be inserted meanwhile."""
    rule = RULES[owner_type]
    conditions = [rule.model.id == owner_id]
    if rule.column is not None:
        conditions.append(rule.model.hotel_id == ctx.hotel_id)
    owner = (
        await db.scalars(select(rule.model).where(*conditions).with_for_update(key_share=True))
    ).one_or_none()
    if owner is None:
        raise NotFound("MEDIA_OWNER_NOT_FOUND")
    return owner


def check_upload(ctx: HotelContext, owner_type: str, owner_id: uuid.UUID | None) -> uuid.UUID:
    """Permission and owner check before the (expensive) image decoding."""
    _require(ctx, RULES[owner_type].edit)
    if owner_type == "hotel":
        return ctx.hotel_id
    if owner_id is None:
        raise ValidationFailed("MEDIA_OWNER_REQUIRED")
    return owner_id


async def decode(raw: bytes, kind: str) -> images.Processed:
    try:
        async with _decoding:
            return await asyncio.to_thread(images.process, raw, kind)
    except images.ImageRejected as e:
        raise ValidationFailed(e.code, params=e.params) from None


async def add(
    db: AsyncSession,
    ctx: HotelContext,
    owner_type: str,
    owner_id: uuid.UUID,
    filename: str | None,
    image: images.Processed,
) -> MediaFile:
    rule = RULES[owner_type]
    await _lock_owner(db, ctx, owner_type, owner_id)
    kind = "logo" if rule.column is None else "photo"
    if rule.column is None:
        # A new logo replaces the current one, which stays for issued invoices.
        for old in await db.scalars(select(MediaFile).where(*_owner_filter(ctx, owner_type, owner_id))):
            old.archived_at = datetime.now(UTC)
        await db.flush()
    else:
        count = await db.scalar(
            select(func.count()).select_from(MediaFile).where(*_owner_filter(ctx, owner_type, owner_id))
        )
        if (count or 0) >= rule.limit:
            raise Conflict("MEDIA_LIMIT_REACHED", params={"limit": rule.limit})
    last = await db.scalar(
        select(func.max(MediaFile.sort_order)).where(*_owner_filter(ctx, owner_type, owner_id))
    )
    m = MediaFile(
        hotel_id=ctx.hotel_id,
        kind=kind,
        filename=clean_filename(filename, image.content_type),
        content_type=image.content_type,
        size=len(image.data),
        width=image.width,
        height=image.height,
        sha256=image.sha256,
        data=image.data,
        thumbnail=image.thumbnail,
        sort_order=(last + 1) if last is not None else 0,
        uploaded_by=ctx.actor.user_id,
    )
    if rule.column:
        setattr(m, rule.column, owner_id)
    db.add(m)
    await db.flush()
    audit.record(
        db,
        ctx.actor,
        "media.upload",
        "media",
        m.id,
        hotel_id=ctx.hotel_id,
        changes={
            "owner": [None, f"{owner_type}:{owner_id}"],
            "filename": [None, m.filename],
            "size": [None, m.size],
        },
    )
    await events.emit(
        db,
        hotel_id=ctx.hotel_id,
        entity=rule.entity,
        action="media_added",
        entity_id=owner_id,
        actor=ctx.actor,
    )
    await db.commit()
    return m


async def reorder(
    db: AsyncSession, ctx: HotelContext, owner_type: str, owner_id: uuid.UUID | None, ids: list[uuid.UUID]
) -> list[MediaFile]:
    rule = RULES[owner_type]
    _require(ctx, rule.edit)
    files = await list_media(db, ctx, owner_type, owner_id)
    if sorted(ids) != sorted(m.id for m in files) or len(set(ids)) != len(ids):
        raise ValidationFailed("MEDIA_ORDER_MISMATCH")
    position = {media_id: i for i, media_id in enumerate(ids)}
    for m in files:
        m.sort_order = position[m.id]
    await db.flush()
    audit.record(db, ctx.actor, "media.reorder", owner_type, owner_id or ctx.hotel_id, hotel_id=ctx.hotel_id)
    await events.emit(
        db,
        hotel_id=ctx.hotel_id,
        entity=rule.entity,
        action="media_reordered",
        entity_id=owner_id or ctx.hotel_id,
        actor=ctx.actor,
    )
    await db.commit()
    return sorted(files, key=lambda m: m.sort_order)


async def delete(db: AsyncSession, ctx: HotelContext, media_id: uuid.UUID) -> None:
    m = await _get(db, ctx, media_id)
    owner_type = owner_type_of(m)
    rule = RULES[owner_type]
    if owner_type == "maintenance_request":
        # Whoever reports a problem may remove their own photos; maintenance
        # managers may remove any.
        own = m.uploaded_by is not None and m.uploaded_by == ctx.actor.user_id
        if not (ctx.has(P.MAINTENANCE_MANAGE) or (own and ctx.has(P.MAINTENANCE_REPORT))):
            raise Forbidden("PERMISSION_DENIED", params={"permission": P.MAINTENANCE_MANAGE})
    else:
        _require(ctx, rule.edit)
    owner_id = owner_id_of(m)
    audit.record(
        db,
        ctx.actor,
        "media.delete",
        "media",
        m.id,
        hotel_id=ctx.hotel_id,
        changes={"owner": [f"{owner_type}:{owner_id}", None], "filename": [m.filename, None]},
    )
    if m.kind == "logo":
        m.archived_at = datetime.now(UTC)
    else:
        await db.delete(m)
    await db.flush()
    await events.emit(
        db,
        hotel_id=ctx.hotel_id,
        entity=rule.entity,
        action="media_removed",
        entity_id=owner_id,
        actor=ctx.actor,
    )
    await db.commit()


# --- documents -----------------------------------------------------------------------


async def current_logo_id(db: AsyncSession, hotel_id: uuid.UUID) -> uuid.UUID | None:
    return await db.scalar(
        select(MediaFile.id).where(
            MediaFile.hotel_id == hotel_id, MediaFile.kind == "logo", MediaFile.archived_at.is_(None)
        )
    )


async def document_logo(db: AsyncSession, doc: dict[str, Any]) -> tuple[bytes, str] | None:
    """The logo a document was built with (archived logos included: an issued
    invoice keeps its logo when the hotel changes it)."""
    raw = (doc.get("hotel") or {}).get("logo_id")
    if not raw:
        return None
    row = (
        await db.execute(
            select(MediaFile.data, MediaFile.content_type).where(
                MediaFile.id == uuid.UUID(str(raw)), MediaFile.kind == "logo"
            )
        )
    ).one_or_none()
    return (row[0], row[1]) if row else None
