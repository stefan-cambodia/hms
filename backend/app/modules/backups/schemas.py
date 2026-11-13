"""Backups screen payloads. The status comes from files written by the backup
service (deploy/scripts/backup-*.sh); unknown or malformed entries are skipped."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.core.schemas import InputModel, OutputModel

BACKUP_FILE_PATTERN = r"^hms-[0-9]{8}T[0-9]{6}Z\.dump$"


class BackupFileOut(OutputModel):
    file: str = Field(pattern=BACKUP_FILE_PATTERN)
    created_at: datetime | None = None
    bytes: int = 0
    sha256: str | None = None
    verified_tables: int | None = None
    verified_hotels: int | None = None
    schema_version: str | None = None
    # schedule | manual | safety (before a restore) | cli | unknown (older files)
    trigger: str = "unknown"
    requested_by: str | None = None
    # Same database schema as the running software: restorable from the
    # screen. Otherwise only with the command-line procedure.
    restorable: bool = False


class BackupRunOut(OutputModel):
    kind: str
    request_id: str | None = None
    trigger: str | None = None
    requested_by: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    status: str
    error: str | None = None
    file: str | None = None
    safety_backup: str | None = None
    bytes: int | None = None


class BackupOperationOut(OutputModel):
    kind: str
    step: str
    request_id: str | None = None
    requested_by: str | None = None
    since: datetime | None = None


class BackupRequestOut(OutputModel):
    id: str
    kind: str
    file: str | None = None
    requested_by: str | None = None
    requested_at: datetime | None = None


class BackupServiceOut(OutputModel):
    # The API and the backup service share a folder (installed stacks).
    connected: bool
    # The service answered recently (or is busy with an operation).
    running: bool
    last_seen: datetime | None = None
    interval_hours: int | None = None
    retention_days: int | None = None
    last_scheduled: datetime | None = None
    next_scheduled: datetime | None = None


class RestorePolicyOut(OutputModel):
    allowed: bool
    # NOT_SUPERADMIN | MULTI_ORGANIZATION
    reason: str | None = None


class BackupsOut(OutputModel):
    service: BackupServiceOut
    current: BackupOperationOut | None
    pending: list[BackupRequestOut]
    backups: list[BackupFileOut]
    runs: list[BackupRunOut]
    schema_version: str | None
    restore: RestorePolicyOut


class RestoreIn(InputModel):
    file: str = Field(pattern=BACKUP_FILE_PATTERN, max_length=64)
    password: str = Field(min_length=1, max_length=200)
    totp_code: str | None = Field(default=None, max_length=12)
    # The hotel's code, typed by hand.
    confirmation: str = Field(min_length=1, max_length=40)


class BackupAcceptedOut(OutputModel):
    request_id: str
