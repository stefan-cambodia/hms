#!/bin/sh
# One verified backup. Runs inside the `backup` container.
#   backup-once.sh [trigger [requested_by [request_id]]]
# trigger: schedule | manual (Backups screen) | safety (before a restore) | cli (default)
# A backup is only kept if it can actually be restored: each dump is restored
# into a scratch database and checked before it is published.
set -eu
umask 077
. /scripts/backup-common.sh
TRIGGER=${1:-cli}
BY=${2:-}
REQUEST=${3:-}
TS=$(date -u +%Y%m%dT%H%M%SZ)
STARTED=$(now_iso)
NAME="hms-$TS.dump"
FILE="$BACKUP_DIR/$NAME"
SCRATCH="hms_verify_$(date -u +%s)"
LAST="$BACKUP_DIR/last-run.json"
mkdir -p "$BACKUP_DIR"

run_json() { # status, error, extra json
  jq -cn --arg id "$REQUEST" --arg trigger "$TRIGGER" --arg by "$BY" --arg started "$STARTED" \
    --arg finished "$(now_iso)" --arg status "$1" --arg error "$2" --arg file "$NAME" --argjson extra "$3" \
    '{kind: "backup", request_id: $id, trigger: $trigger, requested_by: $by, started_at: $started,
      finished_at: $finished, status: $status, error: (if $error == "" then null else $error end),
      file: (if $status == "ok" then $file else null end)} + $extra'
}

fail() {
  dropdb --if-exists "$SCRATCH" 2>/dev/null || true
  rm -f "$FILE.partial"
  printf '{"status":"failed","at":"%s","error":"%s"}\n' "$TS" "$1" > "$LAST"
  record_run "$(run_json failed "$1" '{}')"
  [ "$TRIGGER" = safety ] || idle
  echo "backup FAILED: $1" >&2
  exit 1
}

[ "$TRIGGER" = safety ] || current backup dumping "$REQUEST" "$BY"
pg_dump --format=custom --compress=6 --file="$FILE.partial" || fail "DUMP_FAILED"
pg_restore --list "$FILE.partial" > /dev/null || fail "ARCHIVE_UNREADABLE"
[ "$TRIGGER" = safety ] || current backup verifying "$REQUEST" "$BY"
createdb "$SCRATCH" || fail "CREATEDB_FAILED"
pg_restore --no-owner --dbname="$SCRATCH" "$FILE.partial" || fail "VERIFY_RESTORE_FAILED"
HOTELS=$(psql -At -d "$SCRATCH" -c "SELECT count(*) FROM hotels") || fail "VERIFY_QUERY_FAILED"
TABLES=$(psql -At -d "$SCRATCH" -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
SCHEMA=$(psql -At -d "$SCRATCH" -c "SELECT version_num FROM alembic_version") || fail "SCHEMA_UNKNOWN"
dropdb "$SCRATCH"

mv "$FILE.partial" "$FILE"
SUM=$(sha256sum "$FILE" | cut -d' ' -f1)
echo "$SUM  $NAME" > "$FILE.sha256"
SIZE=$(wc -c < "$FILE")
META=$(jq -cn --arg file "$NAME" --arg at "$(now_iso)" --argjson bytes "$SIZE" --arg sha256 "$SUM" \
  --argjson tables "$TABLES" --argjson hotels "$HOTELS" --arg schema "$SCHEMA" --arg trigger "$TRIGGER" \
  --arg by "$BY" \
  '{file: $file, created_at: $at, bytes: $bytes, sha256: $sha256, verified_tables: $tables,
    verified_hotels: $hotels, schema_version: $schema, trigger: $trigger, requested_by: $by}')
printf '%s\n' "$META" > "${FILE%.dump}.json"
chmod 0644 "${FILE%.dump}.json"
printf '{"status":"ok","at":"%s","file":"%s","bytes":%s,"sha256":"%s","verified_tables":%s,"verified_hotels":%s}\n' \
  "$TS" "$NAME" "$SIZE" "$SUM" "$TABLES" "$HOTELS" > "$LAST"

# Retention: keep N days, but never delete the newest 3 backups.
RETENTION=${BACKUP_RETENTION_DAYS:-30}
ls -1t "$BACKUP_DIR"/hms-*.dump 2>/dev/null | tail -n +4 | while read -r old; do
  if [ -n "$(find "$old" -mtime +"$RETENTION")" ]; then rm -f "$old" "$old.sha256" "${old%.dump}.json"; fi
done
reindex
record_run "$(run_json ok "" "$(jq -cn --argjson bytes "$SIZE" '{bytes: $bytes}')")"
[ "$TRIGGER" = safety ] || idle
echo "backup ok: $FILE ($SIZE bytes, $TABLES tables verified)"
# The safety backup's file name, for the restore that asked for it.
[ "$TRIGGER" != safety ] || printf '%s\n' "$NAME" > "$BACKUP_DIR/.last-safety"
