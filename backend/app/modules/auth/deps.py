"""FastAPI dependencies for authentication and per-hotel authorisation."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Path, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import Actor, HotelContext
from app.core.db import get_db
from app.core.errors import Forbidden, NotFound, Unauthorized
from app.core.security import constant_time_equals
from app.modules.auth import service
from app.modules.auth.models import User, UserSession

SESSION_COOKIE = "hms_session"
CSRF_HEADER = "x-csrf-token"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

DB = Annotated[AsyncSession, Depends(get_db)]


@dataclass
class AuthState:
    user: User
    session: UserSession
    actor: Actor
    via_cookie: bool


def client_ip(request: Request) -> str | None:
    # Caddy is the only ingress and overwrites X-Forwarded-For; uvicorn is started
    # with --forwarded-allow-ips restricted to the proxy, so request.client is trusted.
    return request.client.host if request.client else None


def extract_token(request: Request) -> tuple[str | None, bool]:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None, False
    cookie = request.cookies.get(SESSION_COOKIE)
    return (cookie or None), True


async def get_auth(request: Request, db: DB) -> AuthState:
    cached = getattr(request.state, "auth", None)
    if cached is not None:
        return cached
    token, via_cookie = extract_token(request)
    if not token:
        raise Unauthorized("NOT_AUTHENTICATED", "Authentication required")
    resolved = await service.resolve_session(db, token)
    if resolved is None:
        raise Unauthorized("SESSION_INVALID", "Session expired or revoked")
    session, user = resolved
    if via_cookie and request.method not in _SAFE_METHODS:
        sent = request.headers.get(CSRF_HEADER, "")
        if not sent or not constant_time_equals(sent, session.csrf_token):
            raise Forbidden("CSRF_FAILED", "Missing or invalid CSRF token")
    actor = Actor(
        user_id=user.id,
        organization_id=user.organization_id,
        session_id=session.id,
        is_superadmin=user.is_superadmin,
        ip=client_ip(request),
        request_id=request.headers.get("x-request-id"),
    )
    state = AuthState(user=user, session=session, actor=actor, via_cookie=via_cookie)
    request.state.auth = state
    return state


Auth = Annotated[AuthState, Depends(get_auth)]


async def _permissions_for(request: Request, db: AsyncSession, auth: AuthState) -> dict:
    perms = getattr(request.state, "hotel_permissions", None)
    if perms is None:
        perms = await service.hotel_permissions(db, auth.user)
        request.state.hotel_permissions = perms
    return perms


def require_hotel(
    permission: str | None = None,
) -> Callable[..., Coroutine[Any, Any, HotelContext]]:
    """Dependency factory: user must have access to {hotel_id} (else 404, so
    other hotels' IDs can't be probed) and hold `permission` there (else 403)."""

    async def dependency(
        request: Request,
        db: DB,
        auth: Auth,
        hotel_id: Annotated[uuid.UUID, Path()],
    ) -> HotelContext:
        perms = await _permissions_for(request, db, auth)
        if hotel_id not in perms:
            raise NotFound("HOTEL_NOT_FOUND", "Hotel not found")
        granted = perms[hotel_id]
        if permission is not None and permission not in granted:
            raise Forbidden("PERMISSION_DENIED", "Permission denied", params={"permission": permission})
        return HotelContext(actor=auth.actor, hotel_id=hotel_id, permissions=granted)

    return dependency


def hotel_ctx(permission: str | None = None) -> Any:
    return Annotated[HotelContext, Depends(require_hotel(permission))]
