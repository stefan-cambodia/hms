from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import select

from app.core import audit
from app.core.config import get_settings
from app.modules.auth import service
from app.modules.auth.deps import DB, SESSION_COOKIE, Auth, client_ip
from app.modules.auth.models import UserSession
from app.modules.auth.schemas import (
    HotelAccess,
    LoginIn,
    LoginOut,
    MeOut,
    MeUpdate,
    PasswordChange,
    SessionOut,
    TotpCode,
    TotpDisable,
    TotpSetupOut,
    UserOut,
)
from app.modules.hotels.models import Hotel

router = APIRouter(prefix="/auth", tags=["auth"])


async def _me(db, user, session) -> dict:
    perms = await service.hotel_permissions(db, user)
    hotels = []
    if perms:
        rows = await db.scalars(select(Hotel).where(Hotel.id.in_(perms.keys())).order_by(Hotel.name))
        for h in rows:
            hotels.append(
                HotelAccess(
                    id=h.id,
                    code=h.code,
                    name=h.name,
                    timezone=h.timezone,
                    currency_code=h.currency_code,
                    default_language=h.default_language,
                    permissions=sorted(perms[h.id]),
                )
            )
    return {
        "user": UserOut.model_validate(user),
        "hotels": hotels,
        "csrf_token": session.csrf_token,
        "session_id": session.id,
    }


def _set_session_cookie(response: Response, token: str) -> None:
    s = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=s.session_max_days * 86400,
        httponly=True,
        secure=s.cookie_secure,
        samesite="strict",
        path="/",
    )


@router.post("/login", response_model=LoginOut)
async def login(body: LoginIn, request: Request, response: Response, db: DB) -> dict:
    result = await service.login(
        db,
        email=str(body.email),
        password=body.password,
        totp_code=body.totp_code,
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
        device_label=body.device_label,
    )
    bearer_mode = request.headers.get("x-auth-mode", "").lower() == "bearer"
    if not bearer_mode:
        _set_session_cookie(response, result.token)
    data = await _me(db, result.user, result.session)
    data["token"] = result.token if bearer_mode else None
    return data


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(auth: Auth, db: DB, response: Response) -> Response:
    session = await db.get(UserSession, auth.session.id)
    if session is not None:
        await service.revoke_session(db, auth.actor, session, "logout")
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=MeOut)
async def me(auth: Auth, db: DB) -> dict:
    return await _me(db, auth.user, auth.session)


@router.patch("/me", response_model=MeOut)
async def update_me(body: MeUpdate, auth: Auth, db: DB) -> dict:
    user = auth.user
    before = {"full_name": user.full_name, "preferred_language": user.preferred_language}
    if body.full_name is not None:
        user.full_name = body.full_name
    if body.preferred_language is not None:
        user.preferred_language = body.preferred_language
    after = {"full_name": user.full_name, "preferred_language": user.preferred_language}
    if before != after:
        audit.record(db, auth.actor, "user.update_self", "user", user.id, changes=audit.diff(before, after))
        await db.commit()
    return await _me(db, user, auth.session)


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(body: PasswordChange, auth: Auth, db: DB) -> None:
    await service.change_password(db, auth.actor, auth.user, body.current_password, body.new_password)


@router.get("/me/sessions", response_model=list[SessionOut])
async def my_sessions(auth: Auth, db: DB) -> list[SessionOut]:
    rows = await db.scalars(
        select(UserSession)
        .where(UserSession.user_id == auth.user.id, UserSession.revoked_at.is_(None))
        .order_by(UserSession.last_seen_at.desc())
    )
    out = []
    for s in rows:
        item = SessionOut.model_validate(s)
        item.current = s.id == auth.session.id
        out.append(item)
    return out


@router.delete("/me/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_my_session(session_id: uuid.UUID, auth: Auth, db: DB) -> None:
    s = await service.get_owned_session(db, auth.user, session_id)
    await service.revoke_session(db, auth.actor, s, "user_revoked")


@router.post("/me/totp/setup", response_model=TotpSetupOut)
async def totp_setup(auth: Auth, db: DB) -> TotpSetupOut:
    secret, uri = await service.totp_begin(db, auth.actor, auth.user)
    return TotpSetupOut(secret=secret, otpauth_uri=uri)


@router.post("/me/totp/enable", status_code=status.HTTP_204_NO_CONTENT)
async def totp_enable(body: TotpCode, auth: Auth, db: DB) -> None:
    await service.totp_enable(db, auth.actor, auth.user, body.code)


@router.post("/me/totp/disable", status_code=status.HTTP_204_NO_CONTENT)
async def totp_disable(body: TotpDisable, auth: Auth, db: DB) -> None:
    await service.totp_disable(db, auth.actor, auth.user, body.password)
