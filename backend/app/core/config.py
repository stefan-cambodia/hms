from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Development-only key. Production refuses to start with it (see validator).
_DEV_DATA_KEY = "sfgMB5nIC1Z9DI8Y29mxPxjgpMFPS5EUnlroe82sM_s="


class Settings(BaseSettings):
    """Runtime configuration, read from HMS_* environment variables or `.env`."""

    model_config = SettingsConfigDict(env_prefix="HMS_", env_file=".env", extra="ignore")

    env: Literal["development", "test", "production"] = "development"
    # The API's connection: a login role that is a member of `hms_app`
    # (least privilege, subject to row-level security). Created or updated by
    # `hms db-roles` from this URL's user name and password.
    database_url: str = "postgresql+asyncpg://hms_api:hms_api_dev_password@127.0.0.1:54329/hms"
    # The schema owner, used only by migrations and installation-wide commands
    # (`alembic upgrade`, `hms db-roles`, `hms sync-roles`). Never by the API.
    migration_database_url: str = "postgresql+asyncpg://hms:hms_dev_password@127.0.0.1:54329/hms"
    db_pool_size: int = 10

    # Fernet key used to encrypt recoverable secrets (OTA credentials, TOTP
    # secrets, ID document numbers). Must be backed up separately from the DB.
    data_key: str = _DEV_DATA_KEY

    session_idle_minutes: int = 12 * 60
    session_max_days: int = 7
    cookie_secure: bool = True
    # Origins allowed to open WebSockets / call the API with cookies. Empty means
    # "same origin as the Host header" (the normal reverse-proxy deployment).
    allowed_origins: list[str] = []

    login_max_failures: int = 5
    login_lockout_base_seconds: int = 30
    login_rate_per_minute: int = 20
    # Channel manager background sync (one leader among API processes).
    channel_worker_enabled: bool = True
    channel_worker_interval_seconds: float = 5.0

    enable_docs: bool = True
    media_dir: Path = Path("var/media")
    # Shared with the backup service (deploy/docker-compose.yml): its status
    # files are read from here and backup/restore requests written here.
    # Unset: the Backups screen says the service is not connected.
    backup_control_dir: Path | None = None
    log_level: str = "INFO"

    @model_validator(mode="after")
    def _production_safety(self) -> Settings:
        if self.env == "production":
            if self.data_key == _DEV_DATA_KEY:
                raise ValueError("HMS_DATA_KEY must be set to a unique secret in production")
            if not self.cookie_secure:
                raise ValueError("HMS_COOKIE_SECURE must be true in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
