#!/bin/sh
# One verified backup. Runs inside the `backup` container (postgres client tools).
# A backup is only kept if it can actually be restored: each dump is restored
# into a scratch database and checked before it is published.
set -eu
# Backups contain guest personal data: never world-readable.
umask 077
: "${PGHOST:=db}" "${PGUSER:?}" "${PGDATABASE:?}"
DEST=${BACKUP_DIR:-/backups}
TS=$(date -u +%Y%m%dT%H%M%SZ)
FILE="$DEST/hms-$TS.dump"
SCRATCH="hms_verify_$(date -u +%s)"
STATUS="$DEST/last-run.json"
mkdir -p "$DEST"

fail() {
  dropdb --if-exists "$SCRATCH" 2>/dev/null || true
  rm -f "$FILE.partial"
  printf '{"status":"failed","at":"%s","error":"%s"}\n' "$TS" "$1" > "$STATUS"
  echo "backup FAILED: $1" >&2
  exit 1
}

pg_dump --format=custom --compress=6 --file="$FILE.partial" || fail "pg_dump"
pg_restore --list "$FILE.partial" > /dev/null || fail "archive unreadable"
createdb "$SCRATCH" || fail "createdb scratch"
pg_restore --no-owner --dbname="$SCRATCH" "$FILE.partial" || fail "restore into scratch db"
HOTELS=$(psql -At -d "$SCRATCH" -c "SELECT count(*) FROM hotels") || fail "verification query"
TABLES=$(psql -At -d "$SCRATCH" -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
dropdb "$SCRATCH"

mv "$FILE.partial" "$FILE"
SUM=$(sha256sum "$FILE" | cut -d' ' -f1)
echo "$SUM  $(basename "$FILE")" > "$FILE.sha256"
SIZE=$(wc -c < "$FILE")
printf '{"status":"ok","at":"%s","file":"%s","bytes":%s,"sha256":"%s","verified_tables":%s,"verified_hotels":%s}\n' \
  "$TS" "$(basename "$FILE")" "$SIZE" "$SUM" "$TABLES" "$HOTELS" > "$STATUS"

# Retention: keep N days, but never delete the newest 3 backups.
RETENTION=${BACKUP_RETENTION_DAYS:-30}
ls -1t "$DEST"/hms-*.dump 2>/dev/null | tail -n +4 | while read -r old; do
  if [ -n "$(find "$old" -mtime +"$RETENTION")" ]; then rm -f "$old" "$old.sha256"; fi
done
echo "backup ok: $FILE ($SIZE bytes, $TABLES tables verified)"
