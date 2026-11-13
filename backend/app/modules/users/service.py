"""User, role and session administration, scoped to one hotel.

Anti-escalation rule: an administrator can only grant permissions they hold
themselves in that hotel (super administrators excepted), so a role editor
cannot give anyone, including themselves, more power than they have.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit, events
from app.core.context import HotelContext
from app.core.errors import (
    Conflict,
    Forbidden,
    NotFound,
    ValidationFailed,
    field_error,
    register_constraint,
)
from app.core.permissions import ALL_PERMISSIONS
from app.core.security import hash_password
from app.modules.auth import twofactor
from app.modules.auth.models import Role, RolePermission, User, UserHotelRole, UserSession
from app.modules.auth.service import check_password_policy, revoke_all_sessions, utcnow
from app.modules.users.schemas import (
    RoleIn,
    RoleOut,
    RoleUpdate,
    UserAdminOut,
    UserCreate,
    UserUpdate,
)

register_constraint("uq_users_email", "EMAIL_EXISTS", field="email")
register_constraint("uq_roles_organization_id_code", "ROLE_CODE_EXISTS", field="code")

ONLINE_WINDOW = timedelta(minutes=5)


def _ensure_grantable(ctx: HotelContext, permissions: set[str]) -> None:
    unknown = permissions - ALL_PERMISSIONS
    if unknown:
        raise ValidationFailed(
            "UNKNOWN_PERMISSION",
            "Unknown permission",
            fields=[field_error("permissions", "UNKNOWN_PERMISSION", permission=sorted(unknown)[0])],
        )
    if ctx.actor.is_superadmin:
        return
    excess = permissions - ctx.permissions
    if excess:
        raise Forbidden(
            "CANNOT_GRANT_PERMISSION",
            "Cannot grant a permission you do not hold",
            params={"permission": sorted(excess)[0]},
        )


async def _role_permissions(db: AsyncSession, role_ids: list[uuid.UUID]) -> dict[uuid.UUID, set[str]]:
    out: dict[uuid.UUID, set[str]] = {rid: set() for rid in role_ids}
    if role_ids:
        for rid, perm in await db.execute(
            select(RolePermission.role_id, RolePermission.permission).where(
                RolePermission.role_id.in_(role_ids)
            )
        ):
            out[rid].add(perm)
    return out


async def _org_roles(db: AsyncSession, ctx: HotelContext, role_ids: list[uuid.UUID]) -> list[Role]:
    unique = list(dict.fromkeys(role_ids))
    roles = (
        list(
            await db.scalars(
                select(Role).where(Role.id.in_(unique), Role.organization_id == ctx.actor.organization_id)
            )
        )
        if unique
        else []
    )
    if len(roles) != len(unique):
        raise ValidationFailed(fields=[field_error("role_ids", "ROLE_NOT_FOUND")])
    return roles


# --- Users -------------------------------------------------------------------


async def _hotel_user_ids(db: AsyncSession, hotel_id: uuid.UUID) -> set[uuid.UUID]:
    return set(
        await db.scalars(select(UserHotelRole.user_id).where(UserHotelRole.hotel_id == hotel_id).distinct())
    )


async def _get_hotel_user(db: AsyncSession, ctx: HotelContext, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if (
        user is None
        or user.organization_id != ctx.actor.organization_id
        or (user_id not in await _hotel_user_ids(db, ctx.hotel_id) and not user.is_superadmin)
    ):
        raise NotFound("USER_NOT_FOUND")
    if user.is_superadmin and not ctx.actor.is_superadmin:
        # Only a super administrator may modify another super administrator.
        raise Forbidden("CANNOT_MODIFY_SUPERADMIN")
    return user


async def list_users(db: AsyncSession, ctx: HotelContext) -> list[UserAdminOut]:
    member_ids = await _hotel_user_ids(db, ctx.hotel_id)
    users = list(
        await db.scalars(
            select(User)
            .where(
                User.organization_id == ctx.actor.organization_id,
                User.id.in_(member_ids) | User.is_superadmin.is_(True),
            )
            .order_by(User.full_name)
        )
    )
    roles_by_user: dict[uuid.UUID, list[uuid.UUID]] = {}
    for uid, rid in await db.execute(
        select(UserHotelRole.user_id, UserHotelRole.role_id).where(UserHotelRole.hotel_id == ctx.hotel_id)
    ):
        roles_by_user.setdefault(uid, []).append(rid)
    now = utcnow()
    sessions = dict(
        (
            await db.execute(
                select(UserSession.user_id, func.count())
                .where(UserSession.revoked_at.is_(None), UserSession.expires_at > now)
                .group_by(UserSession.user_id)
            )
        ).all()
    )
    out = []
    for u in users:
        item = UserAdminOut.model_validate(u)
        item.role_ids = roles_by_user.get(u.id, [])
        item.active_sessions = int(sessions.get(u.id, 0))
        out.append(item)
    return out


async def _user_out(db: AsyncSession, ctx: HotelContext, user: User) -> UserAdminOut:
    item = UserAdminOut.model_validate(user)
    item.role_ids = list(
        await db.scalars(
            select(UserHotelRole.role_id).where(
                UserHotelRole.user_id == user.id, UserHotelRole.hotel_id == ctx.hotel_id
            )
        )
    )
    return item


async def create_user(db: AsyncSession, ctx: HotelContext, data: UserCreate) -> UserAdminOut:
    check_password_policy(data.password, field="password")
    roles = await _org_roles(db, ctx, data.role_ids)
    perms = await _role_permissions(db, [r.id for r in roles])
    _ensure_grantable(ctx, set().union(*perms.values()) if perms else set())
    if await db.scalar(select(User.id).where(User.email == str(data.email))):
        raise Conflict(
            "EMAIL_EXISTS", "Email already registered", fields=[field_error("email", "EMAIL_EXISTS")]
        )
    user = User(
        organization_id=ctx.actor.organization_id,
        email=str(data.email),
        full_name=data.full_name,
        password_hash=hash_password(data.password),
        preferred_language=data.preferred_language,
        version=1,
    )
    db.add(user)
    await db.flush()
    db.add_all(UserHotelRole(user_id=user.id, hotel_id=ctx.hotel_id, role_id=r.id) for r in roles)
    audit.record(
        db,
        ctx.actor,
        "user.create",
        "user",
        user.id,
        hotel_id=ctx.hotel_id,
        changes={"email": [None, user.email], "role_ids": [None, [str(r.id) for r in roles]]},
    )
    await events.emit(
        db, hotel_id=ctx.hotel_id, entity="user", action="created", entity_id=user.id, actor=ctx.actor
    )
    await db.commit()
    return await _user_out(db, ctx, user)


async def update_user(
    db: AsyncSession, ctx: HotelContext, user_id: uuid.UUID, data: UserUpdate
) -> UserAdminOut:
    user = await _get_hotel_user(db, ctx, user_id)
    if user.version != data.version:
        raise Conflict("VERSION_CONFLICT", params={"current_version": user.version})
    changes = data.model_dump(exclude_unset=True, exclude={"version"})
    for k in ("full_name", "preferred_language", "is_active"):
        if k in changes and changes[k] is None:
            raise ValidationFailed(fields=[field_error(k, "REQUIRED")])
    if changes.get("is_active") is False and user.id == ctx.actor.user_id:
        raise ValidationFailed(
            "CANNOT_DEACTIVATE_SELF",
            "You cannot deactivate yourself",
            fields=[field_error("is_active", "CANNOT_DEACTIVATE_SELF")],
        )
    before = {k: getattr(user, k) for k in changes}
    for k, v in changes.items():
        setattr(user, k, v)
    delta = audit.diff(before, {k: getattr(user, k) for k in changes})
    if delta:
        if changes.get("is_active") is False:
            await revoke_all_sessions(db, ctx.actor, user.id, "user_deactivated")
        audit.record(db, ctx.actor, "user.update", "user", user.id, hotel_id=ctx.hotel_id, changes=delta)
        await events.emit(
            db, hotel_id=ctx.hotel_id, entity="user", action="updated", entity_id=user.id, actor=ctx.actor
        )
        await db.commit()
    return await _user_out(db, ctx, user)


async def set_user_roles(
    db: AsyncSession, ctx: HotelContext, user_id: uuid.UUID, role_ids: list[uuid.UUID]
) -> UserAdminOut:
    user = await db.get(User, user_id)
    if user is None or user.organization_id != ctx.actor.organization_id:
        raise NotFound("USER_NOT_FOUND")
    if user.is_superadmin and not ctx.actor.is_superadmin:
        raise Forbidden("CANNOT_MODIFY_SUPERADMIN")
    roles = await _org_roles(db, ctx, role_ids)
    current = list(
        await db.scalars(
            select(UserHotelRole.role_id).where(
                UserHotelRole.user_id == user_id, UserHotelRole.hotel_id == ctx.hotel_id
            )
        )
    )
    # Both granting and removing roles require holding their permissions.
    touched = set(current) ^ {r.id for r in roles}
    perms = await _role_permissions(db, list(touched))
    _ensure_grantable(ctx, set().union(*perms.values()) if perms else set())
    if user.id == ctx.actor.user_id and not ctx.actor.is_superadmin and touched:
        raise Forbidden("CANNOT_CHANGE_OWN_ROLES")
    await db.execute(
        delete(UserHotelRole).where(UserHotelRole.user_id == user_id, UserHotelRole.hotel_id == ctx.hotel_id)
    )
    db.add_all(UserHotelRole(user_id=user_id, hotel_id=ctx.hotel_id, role_id=r.id) for r in roles)
    audit.record(
        db,
        ctx.actor,
        "user.roles",
        "user",
        user_id,
        hotel_id=ctx.hotel_id,
        changes={"role_ids": [sorted(map(str, current)), sorted(str(r.id) for r in roles)]},
    )
    await events.emit(
        db, hotel_id=ctx.hotel_id, entity="user", action="updated", entity_id=user_id, actor=ctx.actor
    )
    await db.commit()
    return await _user_out(db, ctx, user)


async def reset_password(db: AsyncSession, ctx: HotelContext, user_id: uuid.UUID, new_password: str) -> None:
    user = await _get_hotel_user(db, ctx, user_id)
    check_password_policy(new_password)
    user.password_hash = hash_password(new_password)
    user.password_changed_at = utcnow()
    user.failed_logins = 0
    user.locked_until = None
    await revoke_all_sessions(db, ctx.actor, user.id, "password_reset")
    audit.record(db, ctx.actor, "user.password_reset", "user", user.id, hotel_id=ctx.hotel_id)
    await db.commit()


async def reset_totp(db: AsyncSession, ctx: HotelContext, user_id: uuid.UUID) -> UserAdminOut:
    """For a user who lost their authenticator: two-factor authentication is
    switched off (they can enable it again) and their sessions end, in case
    the device was stolen. One's own 2FA is switched off in My account, with
    the password."""
    user = await _get_hotel_user(db, ctx, user_id)
    if user.id == ctx.actor.user_id:
        raise Forbidden("USE_MY_ACCOUNT")
    if not user.totp_enabled:
        raise Conflict("TOTP_NOT_ENABLED")
    user.totp_enabled = False
    user.totp_secret = None
    user.totp_last_step = None
    await twofactor.clear_recovery_codes(db, user)
    await revoke_all_sessions(db, ctx.actor, user.id, "totp_reset")
    audit.record(db, ctx.actor, "user.totp_reset", "user", user.id, hotel_id=ctx.hotel_id)
    await db.commit()
    return await _user_out(db, ctx, user)


async def unlock_user(db: AsyncSession, ctx: HotelContext, user_id: uuid.UUID) -> UserAdminOut:
    user = await _get_hotel_user(db, ctx, user_id)
    user.failed_logins = 0
    user.locked_until = None
    audit.record(db, ctx.actor, "user.unlock", "user", user.id, hotel_id=ctx.hotel_id)
    await db.commit()
    return await _user_out(db, ctx, user)


# --- Roles -------------------------------------------------------------------


async def list_roles(db: AsyncSession, ctx: HotelContext) -> list[RoleOut]:
    roles = list(
        await db.scalars(
            select(Role)
            .where(Role.organization_id == ctx.actor.organization_id)
            .order_by(Role.is_system.desc(), Role.name)
        )
    )
    perms = await _role_permissions(db, [r.id for r in roles])
    counts = dict(
        (
            await db.execute(
                select(UserHotelRole.role_id, func.count())
                .where(UserHotelRole.hotel_id == ctx.hotel_id)
                .group_by(UserHotelRole.role_id)
            )
        ).all()
    )
    out = []
    for r in roles:
        item = RoleOut.model_validate(r)
        item.permissions = sorted(perms[r.id])
        item.user_count = int(counts.get(r.id, 0))
        out.append(item)
    return out


async def _role_out(db: AsyncSession, role: Role) -> RoleOut:
    item = RoleOut.model_validate(role)
    item.permissions = sorted((await _role_permissions(db, [role.id]))[role.id])
    return item


async def create_role(db: AsyncSession, ctx: HotelContext, data: RoleIn) -> RoleOut:
    perms = set(data.permissions)
    _ensure_grantable(ctx, perms)
    role = Role(
        organization_id=ctx.actor.organization_id,
        code=data.code,
        name=data.name,
        description=data.description,
        is_system=False,
        require_2fa=data.require_2fa,
        version=1,
    )
    db.add(role)
    await db.flush()
    db.add_all(RolePermission(role_id=role.id, permission=p) for p in sorted(perms))
    audit.record(
        db,
        ctx.actor,
        "role.create",
        "role",
        role.id,
        hotel_id=ctx.hotel_id,
        changes={
            "code": [None, role.code],
            "permissions": [None, sorted(perms)],
            "require_2fa": [None, role.require_2fa],
        },
    )
    await events.emit(
        db, hotel_id=ctx.hotel_id, entity="role", action="created", entity_id=role.id, actor=ctx.actor
    )
    await db.commit()
    return await _role_out(db, role)


async def _get_role(db: AsyncSession, ctx: HotelContext, role_id: uuid.UUID) -> Role:
    role = await db.get(Role, role_id)
    if role is None or role.organization_id != ctx.actor.organization_id:
        raise NotFound("ROLE_NOT_FOUND")
    return role


async def update_role(db: AsyncSession, ctx: HotelContext, role_id: uuid.UUID, data: RoleUpdate) -> RoleOut:
    role = await _get_role(db, ctx, role_id)
    # A system role's name and permissions are fixed (clone it instead); whether
    # it requires two-factor is the organisation's policy, so that may change.
    if role.is_system and data.model_fields_set - {"version", "require_2fa"}:
        raise Forbidden("SYSTEM_ROLE_READONLY", "System roles cannot be modified; clone them")
    if role.version != data.version:
        raise Conflict("VERSION_CONFLICT", params={"current_version": role.version})
    changes: dict = {}
    if data.require_2fa is not None and data.require_2fa != role.require_2fa:
        changes["require_2fa"] = [role.require_2fa, data.require_2fa]
        role.require_2fa = data.require_2fa
    if data.name is not None and data.name != role.name:
        changes["name"] = [role.name, data.name]
        role.name = data.name
    if "description" in data.model_fields_set and data.description != role.description:
        changes["description"] = [role.description, data.description]
        role.description = data.description
    if data.permissions is not None:
        old = (await _role_permissions(db, [role.id]))[role.id]
        new = set(data.permissions)
        _ensure_grantable(ctx, old ^ new)
        if old != new:
            await db.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
            db.add_all(RolePermission(role_id=role.id, permission=p) for p in sorted(new))
            changes["permissions"] = [sorted(old), sorted(new)]
            role.updated_at = utcnow()  # bump version even if only permissions changed
    if changes:
        await db.flush()
        audit.record(db, ctx.actor, "role.update", "role", role.id, hotel_id=ctx.hotel_id, changes=changes)
        await events.emit(
            db, hotel_id=ctx.hotel_id, entity="role", action="updated", entity_id=role.id, actor=ctx.actor
        )
        await db.commit()
        await db.refresh(role)
    return await _role_out(db, role)


async def delete_role(db: AsyncSession, ctx: HotelContext, role_id: uuid.UUID) -> None:
    role = await _get_role(db, ctx, role_id)
    if role.is_system:
        raise Forbidden("SYSTEM_ROLE_READONLY")
    if await db.scalar(select(func.count()).where(UserHotelRole.role_id == role_id)):
        raise Conflict("ROLE_IN_USE", "Role is assigned to users")
    _ensure_grantable(ctx, (await _role_permissions(db, [role.id]))[role.id])
    await db.delete(role)
    audit.record(
        db,
        ctx.actor,
        "role.delete",
        "role",
        role_id,
        hotel_id=ctx.hotel_id,
        changes={"code": [role.code, None]},
    )
    await events.emit(
        db, hotel_id=ctx.hotel_id, entity="role", action="deleted", entity_id=role_id, actor=ctx.actor
    )
    await db.commit()


# --- Sessions ----------------------------------------------------------------


async def hotel_sessions(db: AsyncSession, ctx: HotelContext) -> list[dict]:
    member_ids = await _hotel_user_ids(db, ctx.hotel_id)
    now = utcnow()
    rows = await db.execute(
        select(UserSession, User)
        .join(User, User.id == UserSession.user_id)
        .where(
            User.organization_id == ctx.actor.organization_id,
            User.id.in_(member_ids) | User.is_superadmin.is_(True),
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > now,
        )
        .order_by(UserSession.last_seen_at.desc())
    )
    return [
        {
            "id": s.id,
            "user_id": u.id,
            "user_email": u.email,
            "user_full_name": u.full_name,
            "created_at": s.created_at,
            "last_seen_at": s.last_seen_at,
            "expires_at": s.expires_at,
            "ip": s.ip,
            "user_agent": s.user_agent,
            "device_label": s.device_label,
            "online": now - s.last_seen_at < ONLINE_WINDOW,
            "current": s.id == ctx.actor.session_id,
        }
        for s, u in rows
    ]


async def revoke_hotel_session(db: AsyncSession, ctx: HotelContext, session_id: uuid.UUID) -> None:
    from app.modules.auth.service import revoke_session

    row = (
        await db.execute(
            select(UserSession, User)
            .join(User, User.id == UserSession.user_id)
            .where(UserSession.id == session_id)
        )
    ).one_or_none()
    if row is None:
        raise NotFound("SESSION_NOT_FOUND")
    session, user = row
    if user.organization_id != ctx.actor.organization_id or (
        user.id not in await _hotel_user_ids(db, ctx.hotel_id) and not user.is_superadmin
    ):
        raise NotFound("SESSION_NOT_FOUND")
    if user.is_superadmin and not ctx.actor.is_superadmin:
        raise Forbidden("CANNOT_MODIFY_SUPERADMIN")
    await events.emit(
        db, hotel_id=ctx.hotel_id, entity="session", action="revoked", entity_id=session_id, actor=ctx.actor
    )
    await revoke_session(db, ctx.actor, session, "admin_revoked")
