#!/bin/sh
# Scheduled backups every BACKUP_INTERVAL_HOURS (default 6). Failures are
# recorded in last-run.json and retried at the next interval.
set -u
INTERVAL=$(( ${BACKUP_INTERVAL_HOURS:-6} * 3600 ))
until pg_isready -q; do sleep 2; done
# The API applies migrations on start; back up only once the schema exists.
until psql -Atqc "SELECT 1 FROM alembic_version" >/dev/null 2>&1; do sleep 5; done
while true; do
  /scripts/backup-once.sh || true
  sleep "$INTERVAL"
done
