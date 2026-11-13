"""Backups screen: status of the backup service and requests to it.

The API never touches backup files or other databases itself. The backup
service (a separate container with the PostgreSQL tools) publishes its state
in `<control>/status` and executes the requests the API drops, one JSON file
each, into `<control>/requests`. Restoring therefore works without giving the
API any privilege over the database or Docker.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pyotp
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.config import get_settings
from app.core.context import HotelContext
from app.core.errors import AppError, Conflict, Forbidden, ValidationFailed, field_error
from app.core.security import decrypt_secret
from app.modules.auth.models import User
from app.modules.auth.service import check_current_password
from app.modules.backups.schemas import (
    BackupFileOut,
    BackupOperationOut,
    BackupRequestOut,
    BackupRunOut,
    BackupServiceOut,
    BackupsOut,
    RestoreIn,
    RestorePolicyOut,
)
from app.modules.hotels.models import Hotel

# The service writes its heartbeat every few seconds.
HEARTBEAT_TIMEOUT = timedelta(seconds=60)
# A backup or restore in progress pauses the heartbeat; beyond this it is stuck.
OPERATION_TIMEOUT = timedelta(hours=2)
RUNS_SHOWN = 50


def utcnow() -> datetime:
    return datetime.now(UTC)


def _control() -> Path | None:
    root = get_settings().backup_control_dir
    if root is None or not (root / "status").is_dir():
        return None
    return root


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _models[M: BaseModel](model: type[M], items: Any) -> list[M]:
    out: list[M] = []
    for item in items if isinstance(items, list) else []:
        try:
            out.append(model.model_validate(item))
        except ValidationError:
            continue
    return out


def _model[M: BaseModel](model: type[M], item: Any) -> M | None:
    found = _models(model, [item])
    return found[0] if found else None


def _runs(path: Path) -> list[BackupRunOut]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[-RUNS_SHOWN:]
    except OSError:
        return []
    parsed = []
    for line in lines:
        try:
            parsed.append(json.loads(line))
        except ValueError:
            continue
    return list(reversed(_models(BackupRunOut, parsed)))


def _pending(root: Path) -> list[BackupRequestOut]:
    try:
        files = sorted((root / "requests").glob("*.json"), key=lambda p: p.stat().st_mtime)
    except OSError:
        return []
    return _models(BackupRequestOut, [_read_json(f) for f in files])


async def _schema_version(db: AsyncSession) -> str | None:
    version = await db.scalar(text("SELECT version_num FROM alembic_version"))
    return str(version) if version else None


async def _restore_policy(db: AsyncSession, ctx: HotelContext) -> RestorePolicyOut:
    # A restore replaces the whole database, every hotel included.
    if not ctx.actor.is_superadmin:
        return RestorePolicyOut(allowed=False, reason="NOT_SUPERADMIN")
    if not await db.scalar(select(func.hms_single_organization())):
        return RestorePolicyOut(allowed=False, reason="MULTI_ORGANIZATION")
    return RestorePolicyOut(allowed=True)


async def status(db: AsyncSession, ctx: HotelContext) -> BackupsOut:
    schema = await _schema_version(db)
    policy = await _restore_policy(db, ctx)
    root = _control()
    if root is None:
        return BackupsOut(
            service=BackupServiceOut(connected=False, running=False),
            current=None,
            pending=[],
            backups=[],
            runs=[],
            schema_version=schema,
            restore=policy,
        )
    status_dir = root / "status"
    current = _model(BackupOperationOut, _read_json(status_dir / "current.json"))
    info = _read_json(status_dir / "service.json")
    service = _model(BackupServiceOut, {"connected": True, "running": False, **(info or {})})
    service = service or BackupServiceOut(connected=True, running=False)
    now = utcnow()
    busy = current is not None and current.since is not None and now - current.since < OPERATION_TIMEOUT
    fresh = service.last_seen is not None and now - service.last_seen < HEARTBEAT_TIMEOUT
    service.running = bool(fresh or busy)
    if service.interval_hours:
        base = service.last_scheduled or now
        service.next_scheduled = base + timedelta(hours=service.interval_hours)
    backups = _models(BackupFileOut, _read_json(status_dir / "backups.json"))
    for b in backups:
        b.restorable = schema is not None and b.schema_version == schema
    return BackupsOut(
        service=service,
        current=current,
        pending=_pending(root),
        backups=backups,
        runs=_runs(status_dir / "runs.jsonl"),
        schema_version=schema,
        restore=policy,
    )


def _submit(root: Path, kind: str, user: User, file: str | None = None) -> str:
    request_id = str(uuid.uuid4())
    payload = {
        "id": request_id,
        "kind": kind,
        "file": file,
        "requested_by": user.email,
        "requested_at": utcnow().isoformat(),
    }
    folder = root / "requests"
    tmp = folder / f".{request_id}.tmp"
    try:
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, folder / f"{request_id}.json")  # the service only reads *.json
    except OSError as exc:
        raise AppError(
            "BACKUP_SERVICE_UNAVAILABLE", "Cannot reach the backup service", status_code=503
        ) from exc
    return request_id


def _usable(snapshot: BackupsOut) -> Path:
    root = _control()
    if root is None or not snapshot.service.running:
        raise AppError("BACKUP_SERVICE_UNAVAILABLE", "The backup service is not running", status_code=503)
    if snapshot.current is not None or snapshot.pending:
        raise Conflict("BACKUP_BUSY", "Another backup operation is waiting or running")
    return root


async def request_backup(db: AsyncSession, ctx: HotelContext, user: User) -> str:
    root = _usable(await status(db, ctx))
    request_id = _submit(root, "backup", user)
    audit.record(db, ctx.actor, "backup.request", "backup", request_id, hotel_id=ctx.hotel_id)
    await db.commit()
    return request_id


async def _reauthenticate(user: User, password: str, totp_code: str | None) -> None:
    await check_current_password(user, password, "password")
    if user.totp_enabled:
        secret = decrypt_secret(user.totp_secret) if user.totp_secret else ""
        if not totp_code or not pyotp.TOTP(secret).verify(totp_code, valid_window=1):
            raise ValidationFailed("TOTP_INVALID", fields=[field_error("totp_code", "TOTP_INVALID")])


async def request_restore(db: AsyncSession, ctx: HotelContext, user: User, data: RestoreIn) -> str:
    snapshot = await status(db, ctx)
    if not snapshot.restore.allowed:
        raise Forbidden("RESTORE_NOT_ALLOWED", params={"reason": snapshot.restore.reason})
    await _reauthenticate(user, data.password, data.totp_code)
    hotel = await db.get(Hotel, ctx.hotel_id)
    assert hotel is not None
    if data.confirmation.strip().upper() != hotel.code.upper():
        raise ValidationFailed(
            "CONFIRMATION_MISMATCH", fields=[field_error("confirmation", "CONFIRMATION_MISMATCH")]
        )
    backup = next((b for b in snapshot.backups if b.file == data.file), None)
    if backup is None:
        raise ValidationFailed("BACKUP_NOT_FOUND", fields=[field_error("file", "BACKUP_NOT_FOUND")])
    if not backup.restorable:
        raise Conflict("BACKUP_SCHEMA_MISMATCH", "This backup needs the command-line restore procedure")
    root = _usable(snapshot)
    request_id = _submit(root, "restore", user, data.file)
    audit.record(
        db,
        ctx.actor,
        "backup.restore_request",
        "backup",
        request_id,
        hotel_id=ctx.hotel_id,
        changes={"file": [None, data.file]},
    )
    await db.commit()
    return request_id
