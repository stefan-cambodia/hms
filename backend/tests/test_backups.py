"""Backups screen API. The backup service is simulated by writing the status
files it publishes (its scripts are exercised by the restore drill,
deploy/tests/restore-drill.sh)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.audit import AuditLog
from app.core.config import get_settings
from app.core.db import owner_sessionmaker
from tests.conftest import ADMIN_PASSWORD, Api, error_code
from tests.test_tenancy import other_organisation

SCHEMA = "0010"


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def control(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "status").mkdir()
    (tmp_path / "requests").mkdir()
    monkeypatch.setattr(get_settings(), "backup_control_dir", tmp_path)
    return tmp_path


def service_alive(control: Path, at: datetime | None = None) -> None:
    (control / "status" / "service.json").write_text(
        json.dumps(
            {
                "last_seen": iso(at or datetime.now(UTC)),
                "interval_hours": 6,
                "retention_days": 30,
                "last_scheduled": iso(datetime.now(UTC) - timedelta(hours=1)),
            }
        )
    )


def backup(name: str, schema: str = SCHEMA, trigger: str = "schedule") -> dict:
    return {
        "file": name,
        "created_at": "2026-11-13T02:00:00Z",
        "bytes": 123456,
        "sha256": "ab" * 32,
        "verified_tables": 64,
        "verified_hotels": 1,
        "schema_version": schema,
        "trigger": trigger,
        "requested_by": "",
    }


def publish(control: Path, *backups: dict, runs: list[dict] | None = None) -> None:
    (control / "status" / "backups.json").write_text(json.dumps(list(backups)))
    lines = [json.dumps(r) for r in runs or []] + ["not json"]
    (control / "status" / "runs.jsonl").write_text("\n".join(lines) + "\n")


def requests(control: Path) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted((control / "requests").glob("*.json"))]


GOOD = "hms-20261113T020000Z.dump"
OLD = "hms-20261001T020000Z.dump"


async def test_without_the_backup_service(admin: Api, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(get_settings(), "backup_control_dir", None)
    body = (await admin.get(admin.h("/backups"))).json()
    assert body["service"] == {
        "connected": False,
        "running": False,
        "last_seen": None,
        "interval_hours": None,
        "retention_days": None,
        "last_scheduled": None,
        "next_scheduled": None,
    }
    assert body["schema_version"] == SCHEMA
    r = await admin.post(admin.h("/backups"))
    assert r.status_code == 503 and error_code(r) == "BACKUP_SERVICE_UNAVAILABLE"


async def test_status_and_backup_request(admin: Api, control: Path):
    service_alive(control)
    run = {
        "kind": "backup",
        "trigger": "schedule",
        "started_at": "2026-11-13T02:00:00Z",
        "finished_at": "2026-11-13T02:00:09Z",
        "status": "ok",
        "file": GOOD,
        "bytes": 123456,
    }
    publish(control, backup(GOOD), backup(OLD, schema="0009"), backup("../../etc/passwd"), runs=[run])
    body = (await admin.get(admin.h("/backups"))).json()
    assert body["service"]["running"] is True and body["service"]["interval_hours"] == 6
    # Unknown names are never listed; only same-schema backups are restorable here.
    assert [(b["file"], b["restorable"]) for b in body["backups"]] == [(GOOD, True), (OLD, False)]
    assert [r["status"] for r in body["runs"]] == ["ok"]
    assert body["restore"] == {"allowed": True, "reason": None}

    r = await admin.post(admin.h("/backups"))
    assert r.status_code == 202
    [req] = requests(control)
    assert req["id"] == r.json()["request_id"] and req["kind"] == "backup"
    assert req["requested_by"] == "admin@example.com"
    # One operation at a time.
    again = await admin.post(admin.h("/backups"))
    assert again.status_code == 409 and error_code(again) == "BACKUP_BUSY"
    assert [p["kind"] for p in (await admin.get(admin.h("/backups"))).json()["pending"]] == ["backup"]

    async with owner_sessionmaker()() as db:
        actions = list(await db.scalars(select(AuditLog.action).where(AuditLog.entity_type == "backup")))
    assert actions == ["backup.request"]


async def test_stale_service_refuses_requests(admin: Api, control: Path):
    service_alive(control, at=datetime.now(UTC) - timedelta(minutes=5))
    publish(control, backup(GOOD))
    assert (await admin.get(admin.h("/backups"))).json()["service"]["running"] is False
    r = await admin.post(admin.h("/backups"))
    assert r.status_code == 503
    # Busy with a long operation: the heartbeat pauses, the service is not "down".
    (control / "status" / "current.json").write_text(
        json.dumps({"kind": "backup", "step": "verifying", "since": iso(datetime.now(UTC))})
    )
    body = (await admin.get(admin.h("/backups"))).json()
    assert body["service"]["running"] is True and body["current"]["step"] == "verifying"
    assert (await admin.post(admin.h("/backups"))).status_code == 409


async def test_restore_request_checks(admin: Api, control: Path):
    service_alive(control)
    publish(control, backup(GOOD), backup(OLD, schema="0009"))
    good = {"file": GOOD, "password": ADMIN_PASSWORD, "confirmation": "test"}

    r = await admin.post(admin.h("/backups/restore"), {**good, "password": "wrong"})
    assert r.status_code == 422 and error_code(r) == "INVALID_CURRENT_PASSWORD"
    r = await admin.post(admin.h("/backups/restore"), {**good, "confirmation": "OTHER"})
    assert r.status_code == 422 and error_code(r) == "CONFIRMATION_MISMATCH"
    r = await admin.post(admin.h("/backups/restore"), {**good, "file": "../../etc/passwd"})
    assert r.status_code == 422
    r = await admin.post(admin.h("/backups/restore"), {**good, "file": "hms-20200101T000000Z.dump"})
    assert r.status_code == 422 and error_code(r) == "BACKUP_NOT_FOUND"
    r = await admin.post(admin.h("/backups/restore"), {**good, "file": OLD})
    assert r.status_code == 409 and error_code(r) == "BACKUP_SCHEMA_MISMATCH"
    assert requests(control) == []

    r = await admin.post(admin.h("/backups/restore"), good)  # hotel code, any case
    assert r.status_code == 202, r.text
    [req] = requests(control)
    assert (req["kind"], req["file"]) == ("restore", GOOD)

    # Password guessing through a session is throttled.
    for _ in range(6):
        last = await admin.post(admin.h("/backups/restore"), {**good, "password": "guess"})
    assert last.status_code == 429


async def test_restore_is_for_super_administrators_of_a_single_organisation(
    admin: Api, user_factory, control: Path
):
    service_alive(control)
    publish(control, backup(GOOD))
    receptionist = await user_factory("receptionist")
    assert (await receptionist.get(receptionist.h("/backups"))).status_code == 403
    hotel_admin = await user_factory("hotel_admin")
    assert (await hotel_admin.get(hotel_admin.h("/backups"))).status_code == 403

    # A restore replaces every organisation's data: not from this screen.
    await other_organisation()
    body = (await admin.get(admin.h("/backups"))).json()
    assert body["restore"] == {"allowed": False, "reason": "MULTI_ORGANIZATION"}
    r = await admin.post(
        admin.h("/backups/restore"), {"file": GOOD, "password": ADMIN_PASSWORD, "confirmation": "TEST"}
    )
    assert r.status_code == 403 and error_code(r) == "RESTORE_NOT_ALLOWED"
    assert requests(control) == []
