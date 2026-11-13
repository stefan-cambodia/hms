from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.core.schemas import InputModel, LanguageCode, OutputModel


class LoginIn(InputModel):
    # Not format-validated: login must never reject an identifier on syntax.
    email: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=200)
    totp_code: str | None = Field(None, pattern=r"^\d{6}$")
    # Instead of totp_code when the phone is lost ("abcde-fghjk", case and dashes ignored).
    recovery_code: str | None = Field(None, min_length=10, max_length=20)
    device_label: str | None = Field(None, max_length=100)


class UserOut(OutputModel):
    id: uuid.UUID
    email: str
    full_name: str
    preferred_language: str
    is_superadmin: bool
    totp_enabled: bool
    last_login_at: datetime | None


class HotelAccess(OutputModel):
    id: uuid.UUID
    code: str
    name: str
    timezone: str
    currency_code: str
    default_language: str
    permissions: list[str]


class MeOut(OutputModel):
    user: UserOut
    hotels: list[HotelAccess]
    csrf_token: str
    session_id: uuid.UUID
    # A role of this user requires two-factor; while it is not set up, the
    # session may only set it up (TWO_FACTOR_SETUP_REQUIRED elsewhere).
    two_factor_required: bool = False
    two_factor_setup_required: bool = False
    recovery_codes_left: int | None = None


class LoginOut(MeOut):
    token: str | None = None  # only returned to bearer-mode (non-browser) clients


class MeUpdate(InputModel):
    full_name: str | None = Field(None, min_length=1, max_length=200)
    preferred_language: LanguageCode | None = None


class PasswordChange(InputModel):
    current_password: str = Field(max_length=200)
    new_password: str = Field(max_length=200)


class TotpSetupOut(OutputModel):
    secret: str
    otpauth_uri: str
    qr_svg: str  # data: URI of the link as a QR code


class RecoveryCodesOut(OutputModel):
    codes: list[str]


class PasswordConfirm(InputModel):
    password: str = Field(max_length=200)


class TotpCode(InputModel):
    code: str = Field(pattern=r"^\d{6}$")


class TotpDisable(InputModel):
    password: str = Field(max_length=200)


class SessionOut(OutputModel):
    id: uuid.UUID
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    ip: str | None
    user_agent: str | None
    device_label: str | None
    revoked_at: datetime | None
    revoke_reason: str | None
    current: bool = False
