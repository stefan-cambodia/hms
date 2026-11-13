#!/bin/sh
# Restore a backup into the live database, as requested from the Backups
# screen. Runs inside the `backup` container:
#   backup-restore.sh <file> <requested_by> <request_id>
# Steps: checksum, restore into a new database (which also proves the file
# is usable), same schema version as the running software, then the API's
# connections are closed and refused, a safety backup of the current data is
# taken, and the databases are switched by renaming. The API process keeps
# running and reconnects to the restored data (out of service meanwhile,
# typically under a minute).
set -eu
umask 077
. /scripts/backup-common.sh
FILE=${1:?file}
BY=${2:-}
REQUEST=${3:-}
STARTED=$(now_iso)
TS=$(date -u +%Y%m%dT%H%M%SZ)
NEW="${PGDATABASE}_restore_$(date -u +%s)"
OLD="${PGDATABASE}_replaced_$TS"
SAFETY=""

run_json() { # status, error
  jq -cn --arg id "$REQUEST" --arg by "$BY" --arg started "$STARTED" --arg finished "$(now_iso)" \
    --arg status "$1" --arg error "$2" --arg file "$FILE" --arg safety "$SAFETY" \
    '{kind: "restore", request_id: $id, trigger: "manual", requested_by: $by, started_at: $started,
      finished_at: $finished, status: $status, error: (if $error == "" then null else $error end),
      file: $file, safety_backup: (if $safety == "" then null else $safety end)}'
}
fail() {
  dropdb --if-exists "$NEW" 2>/dev/null || true
  record_run "$(run_json failed "$1")"
  idle
  echo "restore FAILED: $1" >&2
  exit 1
}
sql() { psql -v ON_ERROR_STOP=1 -At -d postgres -c "$1"; }

# The request came through the API; check everything again here.
echo "$FILE" | grep -q "$FILE_RE" || fail "INVALID_FILE"
[ -f "$BACKUP_DIR/$FILE" ] || fail "FILE_NOT_FOUND"
[ -f "$BACKUP_DIR/$FILE.sha256" ] || fail "CHECKSUM_MISSING"
current restore checking "$REQUEST" "$BY"
(cd "$BACKUP_DIR" && sha256sum -c -s "$FILE.sha256") || fail "CHECKSUM_MISMATCH"

current restore loading "$REQUEST" "$BY"
createdb "$NEW" || fail "CREATEDB_FAILED"
pg_restore --no-owner --exit-on-error --dbname="$NEW" "$BACKUP_DIR/$FILE" >/dev/null 2>&1 || fail "RESTORE_FAILED"
WANT=$(psql -At -c "SELECT version_num FROM alembic_version") || fail "LIVE_SCHEMA_UNKNOWN"
GOT=$(psql -At -d "$NEW" -c "SELECT version_num FROM alembic_version") || fail "BACKUP_SCHEMA_UNKNOWN"
# A backup made by another software version must go through the
# command-line procedure (installation guide §6), which runs the migrations.
[ "$WANT" = "$GOT" ] || fail "SCHEMA_MISMATCH"

# Facts the restored data cannot know: the channels hold what was sent after
# the backup, so everything is sent again; and the trail records the restore.
psql -v ON_ERROR_STOP=1 -q -d "$NEW" \
  -v file="$FILE" -v by="$BY" -v at="$(now_iso)" <<'SQL' >/dev/null || fail "PREPARE_FAILED"
DELETE FROM channel_inventory_state;
DELETE FROM channel_rate_state;
UPDATE channel_sync_status SET full_refresh_requested = true;
-- One entry per hotel: a restore changes every hotel's data.
INSERT INTO audit_logs (organization_id, hotel_id, source, action, entity_type, entity_id, changes)
SELECT organization_id, id, 'backup', 'system.restore', 'backup', :'file',
       jsonb_build_object('requested_by', :'by', 'restored_at', :'at')
FROM hotels;
SQL

# Freeze: the API's role may no longer connect (superusers still can), so
# the safety backup below holds exactly the data being replaced.
current restore safety_backup "$REQUEST" "$BY"
unfreeze() { sql "GRANT CONNECT ON DATABASE \"$PGDATABASE\" TO PUBLIC" >/dev/null || true; }
sql "REVOKE CONNECT ON DATABASE \"$PGDATABASE\" FROM PUBLIC" >/dev/null || fail "FREEZE_FAILED"
sql "SELECT count(pg_terminate_backend(a.pid)) FROM pg_stat_activity a JOIN pg_roles r ON r.oid = a.usesysid
     WHERE a.datname = '$PGDATABASE' AND NOT r.rolsuper" >/dev/null
rm -f "$BACKUP_DIR/.last-safety"
if ! /scripts/backup-once.sh safety "$BY" "$REQUEST"; then unfreeze; fail "SAFETY_BACKUP_FAILED"; fi
SAFETY=$(cat "$BACKUP_DIR/.last-safety")

current restore switching "$REQUEST" "$BY"
# No connection at all to the live database any more, then swap the names.
if ! sql "ALTER DATABASE \"$PGDATABASE\" WITH ALLOW_CONNECTIONS false" >/dev/null; then unfreeze; fail "SWITCH_FAILED"; fi
sql "SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity WHERE datname = '$PGDATABASE' AND pid <> pg_backend_pid()" >/dev/null
sleep 1
if ! sql "ALTER DATABASE \"$PGDATABASE\" RENAME TO \"$OLD\"" >/dev/null; then
  sql "ALTER DATABASE \"$PGDATABASE\" WITH ALLOW_CONNECTIONS true" >/dev/null || true
  unfreeze
  fail "SWITCH_FAILED"
fi
if ! sql "ALTER DATABASE \"$NEW\" RENAME TO \"$PGDATABASE\"" >/dev/null; then
  sql "ALTER DATABASE \"$OLD\" RENAME TO \"$PGDATABASE\"" >/dev/null || true
  sql "ALTER DATABASE \"$PGDATABASE\" WITH ALLOW_CONNECTIONS true" >/dev/null || true
  unfreeze
  fail "SWITCH_FAILED"
fi
# The replaced data is in the verified safety backup; free the space.
dropdb --if-exists "$OLD" || echo "warning: could not drop $OLD" >&2

record_run "$(run_json ok "")"
idle
echo "restore ok: $FILE (safety backup $SAFETY)"
