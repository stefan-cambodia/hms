from __future__ import annotations

from fastapi import APIRouter, status

from app.core.permissions import P
from app.modules.auth.deps import DB, Auth, hotel_ctx
from app.modules.backups import service
from app.modules.backups.schemas import BackupAcceptedOut, BackupsOut, RestoreIn

router = APIRouter(prefix="/hotels/{hotel_id}/backups", tags=["backups"])

Manage = hotel_ctx(P.BACKUPS_MANAGE)


@router.get("", response_model=BackupsOut)
async def backups(ctx: Manage, db: DB):
    return await service.status(db, ctx)


@router.post("", response_model=BackupAcceptedOut, status_code=status.HTTP_202_ACCEPTED)
async def backup_now(ctx: Manage, auth: Auth, db: DB):
    return {"request_id": await service.request_backup(db, ctx, auth.user)}


@router.post("/restore", response_model=BackupAcceptedOut, status_code=status.HTTP_202_ACCEPTED)
async def restore(body: RestoreIn, ctx: Manage, auth: Auth, db: DB):
    """Replace ALL data (every hotel) with a backup. Super administrators of a
    single-organisation installation only; password (and 2FA code) and the
    hotel's code are asked again."""
    return {"request_id": await service.request_restore(db, ctx, auth.user, body)}
