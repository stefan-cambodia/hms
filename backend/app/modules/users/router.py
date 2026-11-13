from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status
from sqlalchemy import select

from app.core.audit import AuditLog
from app.core.crud import paginate
from app.core.permissions import PERMISSION_GROUPS, P
from app.core.schemas import Page
from app.modules.auth.deps import DB, Auth, hotel_ctx
from app.modules.auth.models import LoginEvent, User, UserHotelRole
from app.modules.realtime.hub import hub
from app.modules.users import service
from app.modules.users.schemas import (
    AuditLogOut,
    ConnectedSessionOut,
    LoginEventOut,
    PasswordReset,
    PermissionGroupOut,
    RoleIn,
    RoleOut,
    RoleUpdate,
    UserAdminOut,
    UserCreate,
    UserRolesUpdate,
    UserUpdate,
)

router = APIRouter(tags=["users"])

ViewUsers = hotel_ctx(P.USERS_VIEW)
ManageUsers = hotel_ctx(P.USERS_MANAGE)
ManageRoles = hotel_ctx(P.ROLES_MANAGE)
ManageSessions = hotel_ctx(P.SESSIONS_MANAGE)
ViewAudit = hotel_ctx(P.AUDIT_VIEW)

H = "/hotels/{hotel_id}"


@router.get("/permissions", response_model=list[PermissionGroupOut])
async def permission_catalog(_: Auth):
    return [
        PermissionGroupOut(group=g, permissions=[p.value for p in ps]) for g, ps in PERMISSION_GROUPS.items()
    ]


@router.get(H + "/users", response_model=list[UserAdminOut])
async def list_users(ctx: ViewUsers, db: DB):
    return await service.list_users(db, ctx)


@router.post(H + "/users", response_model=UserAdminOut, status_code=status.HTTP_201_CREATED)
async def create_user(body: UserCreate, ctx: ManageUsers, db: DB):
    return await service.create_user(db, ctx, body)


@router.patch(H + "/users/{user_id}", response_model=UserAdminOut)
async def update_user(user_id: uuid.UUID, body: UserUpdate, ctx: ManageUsers, db: DB):
    return await service.update_user(db, ctx, user_id, body)


@router.put(H + "/users/{user_id}/roles", response_model=UserAdminOut)
async def set_user_roles(user_id: uuid.UUID, body: UserRolesUpdate, ctx: ManageUsers, db: DB):
    return await service.set_user_roles(db, ctx, user_id, body.role_ids)


@router.post(H + "/users/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(user_id: uuid.UUID, body: PasswordReset, ctx: ManageUsers, db: DB):
    await service.reset_password(db, ctx, user_id, body.new_password)


@router.post(H + "/users/{user_id}/totp/reset", response_model=UserAdminOut)
async def reset_totp(user_id: uuid.UUID, ctx: ManageUsers, db: DB):
    return await service.reset_totp(db, ctx, user_id)


@router.post(H + "/users/{user_id}/unlock", response_model=UserAdminOut)
async def unlock_user(user_id: uuid.UUID, ctx: ManageUsers, db: DB):
    return await service.unlock_user(db, ctx, user_id)


@router.get(H + "/roles", response_model=list[RoleOut])
async def list_roles(ctx: ViewUsers, db: DB):
    return await service.list_roles(db, ctx)


@router.post(H + "/roles", response_model=RoleOut, status_code=status.HTTP_201_CREATED)
async def create_role(body: RoleIn, ctx: ManageRoles, db: DB):
    return await service.create_role(db, ctx, body)


@router.patch(H + "/roles/{role_id}", response_model=RoleOut)
async def update_role(role_id: uuid.UUID, body: RoleUpdate, ctx: ManageRoles, db: DB):
    return await service.update_role(db, ctx, role_id, body)


@router.delete(H + "/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(role_id: uuid.UUID, ctx: ManageRoles, db: DB):
    await service.delete_role(db, ctx, role_id)


@router.get(H + "/sessions", response_model=list[ConnectedSessionOut])
async def list_sessions(ctx: ManageSessions, db: DB):
    return await service.hotel_sessions(db, ctx)


@router.delete(H + "/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(session_id: uuid.UUID, ctx: ManageSessions, db: DB):
    await service.revoke_hotel_session(db, ctx, session_id)
    hub.revoke_session(session_id)  # close this process's sockets immediately


@router.get(H + "/login-events", response_model=Page[LoginEventOut])
async def login_events(
    ctx: ManageSessions,
    db: DB,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    user_id: uuid.UUID | None = None,
):
    members = select(UserHotelRole.user_id).where(UserHotelRole.hotel_id == ctx.hotel_id)
    superadmins = select(User.id).where(
        User.organization_id == ctx.actor.organization_id, User.is_superadmin.is_(True)
    )
    visible = LoginEvent.user_id.in_(members) | LoginEvent.user_id.in_(superadmins)
    if ctx.actor.is_superadmin:
        # Attempts against unknown emails are only shown to super administrators.
        visible = visible | LoginEvent.user_id.is_(None)
    stmt = select(LoginEvent).where(visible).order_by(LoginEvent.at.desc())
    if user_id:
        stmt = stmt.where(LoginEvent.user_id == user_id)
    items, total = await paginate(db, stmt, limit=limit, offset=offset)
    return Page(
        items=[LoginEventOut.model_validate(i) for i in items], total=total, limit=limit, offset=offset
    )


@router.get(H + "/audit-logs", response_model=Page[AuditLogOut])
async def audit_logs(
    ctx: ViewAudit,
    db: DB,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    entity_type: str | None = None,
    entity_id: str | None = None,
    user_id: uuid.UUID | None = None,
):
    stmt = select(AuditLog).where(AuditLog.hotel_id == ctx.hotel_id).order_by(AuditLog.id.desc())
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    items, total = await paginate(db, stmt, limit=limit, offset=offset)
    return Page(items=[AuditLogOut.model_validate(i) for i in items], total=total, limit=limit, offset=offset)
