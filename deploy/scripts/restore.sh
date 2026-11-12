#!/bin/sh
# Restore a backup into the live database. Run from the deploy/ directory:
#   ./scripts/restore.sh backups/hms-20261112T020000Z.dump
# Stops the API, takes a safety backup of the current state, verifies the
# checksum, restores, and restarts the API.
set -eu
FILE=${1:?usage: restore.sh <backup.dump>}
[ -f "$FILE" ] || { echo "no such file: $FILE" >&2; exit 1; }
if [ -f "$FILE.sha256" ]; then
  (cd "$(dirname "$FILE")" && sha256sum -c "$(basename "$FILE").sha256") || { echo "checksum mismatch" >&2; exit 1; }
fi
printf 'This replaces ALL data in the live database with %s. Type RESTORE to continue: ' "$FILE"
read -r answer
[ "$answer" = "RESTORE" ] || { echo "aborted"; exit 1; }

COMPOSE="docker compose"
echo "Taking a safety backup of the current database..."
$COMPOSE exec -T backup /scripts/backup-once.sh
$COMPOSE stop api
NAME=$(basename "$FILE")
$COMPOSE exec -T backup sh -c "dropdb --force \"\$PGDATABASE\" && createdb \"\$PGDATABASE\" && pg_restore --no-owner --dbname=\"\$PGDATABASE\" \"/backups/$NAME\""
$COMPOSE start api
echo "Restore complete. The API re-applied any newer migrations on start."
