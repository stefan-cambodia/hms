#!/bin/sh
# Fresh screenshot database: demo hotel (`hms seed-demo`) plus realistic
# activity (seed_activity.py). Development database container only.
set -eu
cd "$(dirname "$0")/../../backend"
DB=${SHOTS_DB:-hms_shots}
docker exec hms-dev-db dropdb -U hms --force --if-exists "$DB"
docker exec hms-dev-db createdb -U hms "$DB"
export HMS_MIGRATION_DATABASE_URL="postgresql+asyncpg://hms:hms_dev_password@127.0.0.1:54329/$DB"
export HMS_DATABASE_URL="postgresql+asyncpg://hms_api:hms_api_dev_password@127.0.0.1:54329/$DB"
export HMS_ADMIN_PASSWORD=Demo-Admin-2026 HMS_CHANNEL_WORKER_ENABLED=false
.venv/bin/alembic upgrade head >/dev/null 2>&1
.venv/bin/python -m app.cli db-roles
.venv/bin/python -m app.cli bootstrap --org "Lotus Group" --hotel "Lotus Riverside Hotel" --code LOTUS \
  --admin-email admin@demo.local --admin-name "Sokha Chan" --timezone Asia/Phnom_Penh --currency USD
.venv/bin/python -m app.cli seed-demo --admin-email admin@demo.local
