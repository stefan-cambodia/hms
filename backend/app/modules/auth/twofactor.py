"""Two-factor authentication.

* TOTP codes (RFC 6238, 30-second steps, one step of clock drift either way)
  are accepted once: the last accepted step is stored, so a code seen over a
  shoulder or captured on the network cannot be replayed within its minute.
* Recovery codes: ten one-time codes given when two-factor is turned on (and
  again on request), for the day the phone is lost. 10 characters from a
  31-symbol alphabet (about 50 bits each); only an HMAC-SHA256 keyed with a key
  derived from HMS_DATA_KEY is stored, so a copy of the database alone is not
  enough to guess them.
* A role can require two-factor: its holders who have not set it up yet can
  sign in, but may only set it up (app/modules/auth/deps.py).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from datetime import UTC, datetime

import pyotp
import segno
from sqlalchemy import delete, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import decrypt_secret
from app.modules.auth.models import RecoveryCode, Role, User, UserHotelRole

RECOVERY_CODE_COUNT = 10
_ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"  # no 0/o, 1/l/i: read aloud and typed without doubt
STEP_SECONDS = 30


# --- TOTP -----------------------------------------------------------------------------


def totp_step(secret: str, code: str, now: float | None = None) -> int | None:
    """The time step whose code `code` is (current step ± 1), or None."""
    current = int((time.time() if now is None else now) // STEP_SECONDS)
    totp = pyotp.TOTP(secret)
    for step in (current - 1, current, current + 1):
        if hmac.compare_digest(totp.generate_otp(step), code):
            return step
    return None


def accept_totp(user: User, code: str) -> bool:
    """Check a code and consume its time step (the caller commits)."""
    if not user.totp_secret:
        return False
    step = totp_step(decrypt_secret(user.totp_secret), code)
    if step is None or (user.totp_last_step is not None and step <= user.totp_last_step):
        return False
    user.totp_last_step = step
    return True


def qr_svg(otpauth_uri: str) -> str:
    """The set-up link as a QR code (SVG data URI) for the authenticator app."""
    return segno.make(otpauth_uri, error="m").svg_data_uri(scale=5, border=2, dark="#0f172a")


# --- Recovery codes ---------------------------------------------------------------------


def _key() -> bytes:
    return hashlib.sha256(b"hms-recovery-codes:" + get_settings().data_key.encode()).digest()


def normalize(code: str) -> str:
    return "".join(ch for ch in code.lower() if ch.isalnum())


def hash_recovery_code(code: str) -> str:
    return hmac.new(_key(), normalize(code).encode(), hashlib.sha256).hexdigest()


def new_recovery_codes() -> list[str]:
    codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = "".join(secrets.choice(_ALPHABET) for _ in range(10))
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes


async def replace_recovery_codes(db: AsyncSession, user: User) -> list[str]:
    """New codes; earlier ones stop working. Returned once, never stored in clear."""
    await clear_recovery_codes(db, user)
    codes = new_recovery_codes()
    db.add_all(RecoveryCode(user_id=user.id, code_hash=hash_recovery_code(c)) for c in codes)
    return codes


async def clear_recovery_codes(db: AsyncSession, user: User) -> None:
    await db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))


async def use_recovery_code(db: AsyncSession, user: User, code: str) -> bool:
    """Consume an unused code (the caller commits). Two sign-ins racing with the
    same code: the row lock makes the second one find it used."""
    if len(normalize(code)) != 10:
        return False
    row = (
        await db.scalars(
            select(RecoveryCode)
            .where(
                RecoveryCode.user_id == user.id,
                RecoveryCode.used_at.is_(None),
                RecoveryCode.code_hash == hash_recovery_code(code),
            )
            .with_for_update()
        )
    ).first()
    if row is None:
        return False
    row.used_at = datetime.now(UTC)
    return True


async def recovery_codes_left(db: AsyncSession, user: User) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(RecoveryCode)
            .where(RecoveryCode.user_id == user.id, RecoveryCode.used_at.is_(None))
        )
        or 0
    )


# --- Requirement by role -------------------------------------------------------------------


async def required_for(db: AsyncSession, user: User) -> bool:
    """Does one of the user's roles, in any hotel, require two-factor?"""
    return bool(
        await db.scalar(
            select(
                exists().where(
                    UserHotelRole.user_id == user.id,
                    UserHotelRole.role_id == Role.id,
                    Role.require_2fa.is_(True),
                )
            )
        )
    )
