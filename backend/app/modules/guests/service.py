from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit, crud, events
from app.core.context import HotelContext
from app.core.errors import ValidationFailed, field_error
from app.core.permissions import P
from app.core.security import decrypt_secret, encrypt_secret
from app.modules.guests.models import Guest
from app.modules.guests.schemas import GuestDuplicateOut, GuestIn, GuestOut, GuestUpdate

GUEST_FIELDS = (
    "first_name",
    "last_name",
    "email",
    "phone",
    "nationality",
    "preferred_language",
    "address",
    "city",
    "country_code",
    "date_of_birth",
    "vip_level",
    "tags",
    "preferences",
    "notes",
    "id_document_type",
    "id_document_number",
    "id_document_country",
    "id_document_expiry",
    "marketing_consent",
)
SENSITIVE = (
    "date_of_birth",
    "id_document_type",
    "id_document_number",
    "id_document_country",
    "id_document_expiry",
)


def normalize_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    return digits[-15:] or None


def guest_out(g: Guest, ctx: HotelContext) -> GuestOut:
    out = GuestOut.model_validate(g, from_attributes=True)
    out.has_id_document = g.id_document_number is not None
    if ctx.has(P.GUESTS_VIEW_SENSITIVE):
        out.id_document_number = decrypt_secret(g.id_document_number) if g.id_document_number else None
    else:
        for f in SENSITIVE:
            setattr(out, f, None)
    return out


def _apply(g: Guest, values: dict[str, Any], ctx: HotelContext) -> None:
    sensitive_touched = any(f in values for f in SENSITIVE)
    if sensitive_touched and not ctx.has(P.GUESTS_VIEW_SENSITIVE):
        raise ValidationFailed(
            "SENSITIVE_FIELDS_FORBIDDEN",
            "Not allowed to edit identity data",
            fields=[field_error("id_document_number", "SENSITIVE_FIELDS_FORBIDDEN")],
        )
    for k, v in values.items():
        if k == "id_document_number":
            current = decrypt_secret(g.id_document_number) if g.id_document_number else None
            if v == current:
                continue  # unchanged: keep the ciphertext (and the audit log quiet)
            v = encrypt_secret(v) if v else None
        setattr(g, k, v)
    if "phone" in values:
        g.phone_normalized = normalize_phone(g.phone)


async def create_guest(db: AsyncSession, ctx: HotelContext, data: GuestIn, *, commit: bool = True) -> Guest:
    g = Guest(hotel_id=ctx.hotel_id, version=1)
    values = data.model_dump(exclude_unset=False)
    if not any(values.get(f) for f in SENSITIVE):
        for f in SENSITIVE:
            values.pop(f, None)
    _apply(g, values, ctx)
    db.add(g)
    await db.flush()
    audit.record(
        db,
        ctx.actor,
        "guest.create",
        "guest",
        g.id,
        hotel_id=ctx.hotel_id,
        changes=audit.diff(None, {"first_name": g.first_name, "last_name": g.last_name}),
    )
    await events.emit(
        db, hotel_id=ctx.hotel_id, entity="guest", action="created", entity_id=g.id, actor=ctx.actor
    )
    if commit:
        await db.commit()
    return g


async def update_guest(db: AsyncSession, ctx: HotelContext, guest_id: uuid.UUID, data: GuestUpdate) -> Guest:
    g = await crud.get_scoped(db, Guest, ctx.hotel_id, guest_id, code="GUEST_NOT_FOUND")
    crud.check_version(g, data.version)
    changes = data.model_dump(exclude_unset=True, exclude={"version"})
    for k in ("first_name", "last_name", "vip_level", "tags", "preferences", "marketing_consent"):
        if k in changes and changes[k] is None:
            raise ValidationFailed(fields=[field_error(k, "REQUIRED")])
    before = crud.snapshot(g, GUEST_FIELDS)
    _apply(g, changes, ctx)
    delta = audit.diff(before, crud.snapshot(g, GUEST_FIELDS))
    if delta:
        await db.flush()
        audit.record(db, ctx.actor, "guest.update", "guest", g.id, hotel_id=ctx.hotel_id, changes=delta)
        await events.emit(
            db,
            hotel_id=ctx.hotel_id,
            entity="guest",
            action="updated",
            entity_id=g.id,
            version=g.version,
            actor=ctx.actor,
        )
        await db.commit()
        await db.refresh(g)
    return g


async def search_guests(
    db: AsyncSession, ctx: HotelContext, q: str | None, *, limit: int, offset: int
) -> tuple[list[Guest], int]:
    stmt = select(Guest).where(Guest.hotel_id == ctx.hotel_id, Guest.merged_into_id.is_(None))
    if q and q.strip():
        term = q.strip()
        full = func.lower(Guest.first_name + " " + Guest.last_name)
        conds = [
            full.ilike(f"%{term.lower()}%"),
            func.similarity(full, term.lower()) > 0.3,
            Guest.email.ilike(f"%{term}%"),
        ]
        digits = normalize_phone(term)
        if digits and len(digits) >= 4:
            conds.append(Guest.phone_normalized.like(f"%{digits}%"))
        stmt = stmt.where(or_(*conds)).order_by(func.similarity(full, term.lower()).desc(), Guest.last_name)
    else:
        stmt = stmt.order_by(Guest.created_at.desc())
    items, total = await crud.paginate(db, stmt, limit=limit, offset=offset)
    return list(items), total


async def find_duplicates(
    db: AsyncSession,
    ctx: HotelContext,
    *,
    first_name: str,
    last_name: str,
    email: str | None,
    phone: str | None,
    exclude_id: uuid.UUID | None = None,
) -> list[GuestDuplicateOut]:
    """Likely duplicates: same email, same phone, or a very similar full name."""
    full = func.lower(Guest.first_name + " " + Guest.last_name)
    name = f"{first_name} {last_name}".lower().strip()
    digits = normalize_phone(phone)
    conds = [func.similarity(full, name) > 0.55]
    if email:
        conds.append(Guest.email == email)
    if digits and len(digits) >= 6:
        conds.append(Guest.phone_normalized == digits)
    stmt = (
        select(Guest, func.similarity(full, name))
        .where(Guest.hotel_id == ctx.hotel_id, Guest.merged_into_id.is_(None), or_(*conds))
        .order_by(func.similarity(full, name).desc())
        .limit(10)
    )
    if exclude_id:
        stmt = stmt.where(Guest.id != exclude_id)
    out = []
    for g, sim in await db.execute(stmt):
        reasons = []
        if email and g.email and g.email.lower() == email.lower():
            reasons.append("same_email")
        if digits and g.phone_normalized == digits:
            reasons.append("same_phone")
        if sim > 0.55:
            reasons.append("similar_name")
        score = min(1.0, float(sim) + 0.5 * ("same_email" in reasons) + 0.4 * ("same_phone" in reasons))
        out.append(GuestDuplicateOut(guest=guest_out(g, ctx), reasons=reasons, score=round(score, 2)))
    return sorted(out, key=lambda d: d.score, reverse=True)
