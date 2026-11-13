#!/bin/sh
# Backup service (entry point of the `backup` container): a verified backup
# every BACKUP_INTERVAL_HOURS (default 6), plus the backups and restores
# requested from the Backups screen. One operation at a time.
#
# Requests: the API writes <uuid>.json files into $CONTROL/requests (the only
# thing it may write here). Status: this service writes $CONTROL/status/*,
# which the API reads.
set -u
. /scripts/backup-common.sh
API_UID=${HMS_API_UID:-10001}
INTERVAL=$(( ${BACKUP_INTERVAL_HOURS:-6} * 3600 ))
mkdir -p "$REQUESTS" "$STATUS" "$BACKUP_DIR"
chown "$API_UID" "$REQUESTS" && chmod 0700 "$REQUESTS"
chmod 0755 "$CONTROL" "$STATUS"
idle

until pg_isready -q; do sleep 2; done
# Migrations run in the `migrate` service; back up only once the schema exists.
until psql -Atqc "SELECT 1 FROM alembic_version" >/dev/null 2>&1; do sleep 5; done
reindex
LAST_FILE="$STATUS/.last-scheduled"
last=$(cat "$LAST_FILE" 2>/dev/null || echo 0)

handle() { # request file
  req=$1
  id=$(jq -r '.id // ""' "$req" 2>/dev/null || true)
  kind=$(jq -r '.kind // ""' "$req" 2>/dev/null || true)
  file=$(jq -r '.file // ""' "$req" 2>/dev/null || true)
  by=$(jq -r '.requested_by // ""' "$req" 2>/dev/null | tr -cd 'A-Za-z0-9@._+-' | cut -c1-200)
  rm -f "$req"
  if ! echo "$id" | grep -q "$UUID_RE"; then
    echo "ignoring malformed request $(basename "$req")" >&2
    return
  fi
  case "$kind" in
    backup) /scripts/backup-once.sh manual "$by" "$id" || true ;;
    restore) /scripts/backup-restore.sh "$file" "$by" "$id" || true ;;
    *) echo "ignoring request $id of unknown kind" >&2 ;;
  esac
}

while true; do
  publish service.json "$(jq -cn --arg at "$(now_iso)" --argjson hours "${BACKUP_INTERVAL_HOURS:-6}" \
    --argjson days "${BACKUP_RETENTION_DAYS:-30}" --argjson last "$last" \
    '{last_seen: $at, interval_hours: $hours, retention_days: $days,
      last_scheduled: (if $last == 0 then null else ($last | todate) end)}')"
  for req in $(ls -1tr "$REQUESTS"/*.json 2>/dev/null); do
    handle "$req"
  done
  now=$(date -u +%s)
  if [ $((now - last)) -ge "$INTERVAL" ]; then
    /scripts/backup-once.sh schedule || true
    last=$now
    echo "$last" > "$LAST_FILE"
  fi
  sleep 5
done
