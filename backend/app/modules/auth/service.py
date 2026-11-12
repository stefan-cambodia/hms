from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pyotp
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.config import get_settings
from app.core.context import Actor
from app.core.errors import (
    AppError,
    Forbidden,
    NotFound,
    Unauthorized,
    ValidationFailed,
    field_error,
)
from app.core.permissions import ALL_PERMISSIONS
from app.core.ratelimit import SlidingWindowLimiter
from app.core.security import (
    decrypt_secret,
    encrypt_secret,
    hash_password,
    hash_token,
    needs_rehash,
    new_token,
    password_policy_violation,
    verify_password,
)
from app.modules.auth.models import LoginEvent, RolePermission, User, UserHotelRole, UserSession
from app.modules.hotels.models import Hotel

login_limiter = SlidingWindowLimiter(get_settings().login_rate_per_minute, 60)
TOUCH_INTERVAL = timedelta(seconds=60)


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class LoginResult:
    user: User
    session: UserSession
    token: str


def _lockout_delay(failures: int) -> timedelta:
    s = get_settings()
    over = failures - s.login_max_failures
    return timedelta(seconds=min(s.login_lockout_base_seconds * (2**over), 3600))


async def login(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    totp_code: str | None,
    ip: str | None,
    user_agent: str | None,
    device_label: str | None,
) -> LoginResult:
    if not login_limiter.hit(f"ip:{ip}"):
        raise AppError("TOO_MANY_ATTEMPTS", "Too many login attempts", status_code=429)

    now = utcnow()
    user = (await db.scalars(select(User).where(User.email == email))).one_or_none()

    async def fail(reason: str, code: str = "INVALID_CREDENTIALS", count: bool = True) -> None:
        if user is not None and count:
            user.failed_logins += 1
            if user.failed_logins >= get_settings().login_max_failures:
                user.locked_until = now + _lockout_delay(user.failed_logins)
        db.add(
            LoginEvent(
                user_id=user.id if user else None,
                email=email[:320],
                success=False,
                reason=reason,
                ip=ip,
                user_agent=(user_agent or "")[:400],
            )
        )
        await db.commit()
        raise Unauthorized(code, "Login failed")

    if user is not None and user.locked_until and user.locked_until > now:
        retry = int((user.locked_until - now).total_seconds()) + 1
        db.add(
            LoginEvent(
                user_id=user.id,
                email=email[:320],
                success=False,
                reason="locked",
                ip=ip,
                user_agent=(user_agent or "")[:400],
            )
        )
        await db.commit()
        raise AppError(
            "ACCOUNT_LOCKED", "Account temporarily locked", status_code=429, params={"retry_after": retry}
        )

    # Always run a hash verification so timing doesn't reveal unknown emails.
    password_ok = verify_password(user.password_hash if user else None, password)
    if user is None:
        await fail("unknown_user")
    assert user is not None
    if not password_ok:
        await fail("bad_password")
    if not user.is_active:
        await fail("inactive", count=False)
    if user.totp_enabled:
        if not totp_code:
            # Password was right: don't count, but don't create a session either.
            raise Unauthorized("TOTP_REQUIRED", "Two-factor code required")
        secret = decrypt_secret(user.totp_secret) if user.totp_secret else ""
        if not pyotp.TOTP(secret).verify(totp_code, valid_window=1):
            await fail("bad_totp", code="TOTP_INVALID")

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = now

    token = new_token()
    session = UserSession(
        id=uuid.uuid4(),
        user_id=user.id,
        token_hash=hash_token(token),
        csrf_token=new_token(),
        last_seen_at=now,
        expires_at=now + timedelta(days=get_settings().session_max_days),
        ip=ip,
        user_agent=(user_agent or "")[:400],
        device_label=(device_label or "")[:100] or None,
    )
    db.add(session)
    db.add(
        LoginEvent(
            user_id=user.id, email=email[:320], success=True, ip=ip, user_agent=(user_agent or "")[:400]
        )
    )
    actor = Actor(user_id=user.id, organization_id=user.organization_id, session_id=session.id, ip=ip)
    audit.record(db, actor, "login", "user", user.id)
    await db.commit()
    return LoginResult(user=user, session=session, token=token)


async def resolve_session(db: AsyncSession, token: str) -> tuple[UserSession, User] | None:
    row = (
        await db.execute(
            select(UserSession, User)
            .join(User, User.id == UserSession.user_id)
            .where(UserSession.token_hash == hash_token(token))
        )
    ).one_or_none()
    if row is None:
        return None
    session, user = row
    now = utcnow()
    idle_limit = timedelta(minutes=get_settings().session_idle_minutes)
    if (
        session.revoked_at is not None
        or session.expires_at <= now
        or session.last_seen_at + idle_limit <= now
        or not user.is_active
    ):
        return None
    if now - session.last_seen_at > TOUCH_INTERVAL:
        await db.execute(update(UserSession).where(UserSession.id == session.id).values(last_seen_at=now))
        await db.commit()
        session.last_seen_at = now
    return session, user


async def is_session_active(db: AsyncSession, session_id: uuid.UUID) -> bool:
    s = await db.get(UserSession, session_id, populate_existing=True)
    return bool(s and s.revoked_at is None and s.expires_at > utcnow())


async def revoke_session(db: AsyncSession, actor: Actor, session: UserSession, reason: str) -> None:
    if session.revoked_at is None:
        session.revoked_at = utcnow()
        session.revoked_by = actor.user_id
        session.revoke_reason = reason
        audit.record(
            db,
            actor,
            "session.revoke",
            "user_session",
            session.id,
            changes={"user_id": [None, str(session.user_id)], "reason": [None, reason]},
        )
    await db.commit()


async def revoke_all_sessions(
    db: AsyncSession,
    actor: Actor,
    user_id: uuid.UUID,
    reason: str,
    *,
    except_session: uuid.UUID | None = None,
) -> int:
    stmt = (
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=utcnow(), revoked_by=actor.user_id, revoke_reason=reason)
    )
    if except_session is not None:
        stmt = stmt.where(UserSession.id != except_session)
    result = await db.execute(stmt)
    return result.rowcount or 0  # type: ignore[attr-defined]


def check_password_policy(password: str, field: str = "new_password") -> None:
    violation = password_policy_violation(password)
    if violation:
        raise ValidationFailed(
            violation, "Password does not meet policy", fields=[field_error(field, violation)]
        )


async def change_password(db: AsyncSession, actor: Actor, user: User, current: str, new: str) -> None:
    if not verify_password(user.password_hash, current):
        raise ValidationFailed(
            "INVALID_CURRENT_PASSWORD",
            "Current password is wrong",
            fields=[field_error("current_password", "INVALID_CURRENT_PASSWORD")],
        )
    check_password_policy(new)
    user.password_hash = hash_password(new)
    user.password_changed_at = utcnow()
    await revoke_all_sessions(db, actor, user.id, "password_changed", except_session=actor.session_id)
    audit.record(db, actor, "user.password_change", "user", user.id)
    await db.commit()


# --- TOTP -------------------------------------------------------------------


async def totp_begin(db: AsyncSession, actor: Actor, user: User) -> tuple[str, str]:
    if user.totp_enabled:
        raise AppError("TOTP_ALREADY_ENABLED", "Two-factor already enabled", status_code=409)
    secret = pyotp.random_base32()
    user.totp_secret = encrypt_secret(secret)
    await db.commit()
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name="HMS")
    return secret, uri


async def totp_enable(db: AsyncSession, actor: Actor, user: User, code: str) -> None:
    if user.totp_enabled or not user.totp_secret:
        raise AppError("TOTP_NOT_STARTED", "Start two-factor setup first", status_code=409)
    if not pyotp.TOTP(decrypt_secret(user.totp_secret)).verify(code, valid_window=1):
        raise ValidationFailed("TOTP_INVALID", "Invalid code", fields=[field_error("code", "TOTP_INVALID")])
    user.totp_enabled = True
    audit.record(db, actor, "user.totp_enable", "user", user.id)
    await db.commit()


async def totp_disable(db: AsyncSession, actor: Actor, user: User, password: str) -> None:
    if not verify_password(user.password_hash, password):
        raise ValidationFailed(
            "INVALID_CURRENT_PASSWORD",
            "Wrong password",
            fields=[field_error("password", "INVALID_CURRENT_PASSWORD")],
        )
    user.totp_enabled = False
    user.totp_secret = None
    audit.record(db, actor, "user.totp_disable", "user", user.id)
    await db.commit()


# --- Authorisation ----------------------------------------------------------


async def hotel_permissions(db: AsyncSession, user: User) -> dict[uuid.UUID, frozenset[str]]:
    """Effective permissions per accessible hotel."""
    if user.is_superadmin:
        hotel_ids = await db.scalars(select(Hotel.id).where(Hotel.organization_id == user.organization_id))
        return {hid: ALL_PERMISSIONS for hid in hotel_ids}
    rows = await db.execute(
        select(UserHotelRole.hotel_id, RolePermission.permission)
        .join(RolePermission, RolePermission.role_id == UserHotelRole.role_id)
        .join(Hotel, Hotel.id == UserHotelRole.hotel_id)
        .where(UserHotelRole.user_id == user.id, Hotel.organization_id == user.organization_id)
    )
    result: dict[uuid.UUID, set[str]] = {}
    for hotel_id, perm in rows:
        if perm in ALL_PERMISSIONS:  # ignore grants for retired permission codes
            result.setdefault(hotel_id, set()).add(perm)
    # Hotels where the user has a role with zero permissions still count as accessible.
    for (hid,) in await db.execute(select(UserHotelRole.hotel_id).where(UserHotelRole.user_id == user.id)):
        result.setdefault(hid, set())
    return {k: frozenset(v) for k, v in result.items()}


async def get_owned_session(db: AsyncSession, user: User, session_id: uuid.UUID) -> UserSession:
    s = await db.get(UserSession, session_id)
    if s is None or s.user_id != user.id:
        raise NotFound("SESSION_NOT_FOUND")
    return s


def ensure(condition: bool, code: str = "PERMISSION_DENIED") -> None:
    if not condition:
        raise Forbidden(code)
