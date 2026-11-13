from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from app.core.schemas import Code, InputModel, LanguageCode, OutputModel, StaffEmail, UpdateModel


class UserCreate(InputModel):
    email: StaffEmail
    full_name: str = Field(min_length=1, max_length=200)
    password: str = Field(max_length=200)
    preferred_language: LanguageCode = "en"
    role_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)


class UserUpdate(UpdateModel):
    full_name: str | None = Field(None, min_length=1, max_length=200)
    preferred_language: LanguageCode | None = None
    is_active: bool | None = None


class UserRolesUpdate(InputModel):
    role_ids: list[uuid.UUID] = Field(max_length=20)


class PasswordReset(InputModel):
    new_password: str = Field(max_length=200)


class UserAdminOut(OutputModel):
    id: uuid.UUID
    email: str
    full_name: str
    preferred_language: str
    is_active: bool
    is_superadmin: bool
    totp_enabled: bool
    last_login_at: datetime | None
    locked_until: datetime | None
    version: int
    role_ids: list[uuid.UUID] = Field(default_factory=list)
    active_sessions: int = 0


class RoleIn(InputModel):
    code: Code
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(None, max_length=1000)
    permissions: list[str] = Field(default_factory=list, max_length=200)
    require_2fa: bool = False


class RoleUpdate(UpdateModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=1000)
    permissions: list[str] | None = Field(None, max_length=200)
    require_2fa: bool | None = None


class RoleOut(OutputModel):
    id: uuid.UUID
    code: str
    name: str
    description: str | None
    is_system: bool
    require_2fa: bool
    version: int
    permissions: list[str] = Field(default_factory=list)
    user_count: int = 0


class PermissionGroupOut(OutputModel):
    group: str
    permissions: list[str]


class ConnectedSessionOut(OutputModel):
    id: uuid.UUID
    user_id: uuid.UUID
    user_email: str
    user_full_name: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    ip: str | None
    user_agent: str | None
    device_label: str | None
    online: bool
    current: bool = False


class LoginEventOut(OutputModel):
    id: int
    at: datetime
    user_id: uuid.UUID | None
    email: str
    success: bool
    reason: str | None
    ip: str | None
    user_agent: str | None


class AuditLogOut(OutputModel):
    id: int
    at: datetime
    user_id: uuid.UUID | None
    source: str
    action: str
    entity_type: str
    entity_id: str | None
    changes: dict[str, Any] | None
    ip: str | None
