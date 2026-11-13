#!/usr/bin/env bash
# Restore drill on a throwaway copy of the production stack (project
# "hms-drill", its own volumes and ports; removed at the end unless KEEP=1).
#
# Checks, through the API exactly as the Backups screen uses it:
#   * the stack starts in production mode: migrations by the `migrate` service,
#     the API on its least-privilege role (it refuses to start otherwise);
#   * a backup requested from the API is made and verified by the service;
#   * a restore requested from the API brings the data back to that backup,
#     keeps a safety backup of what it replaced, records itself in the audit
#     trail, and the API works again afterwards without being restarted;
#   * a client cannot choose the IP address the API sees (X-Forwarded-For).
#
#   deploy/tests/restore-drill.sh       (needs docker compose, curl, jq, openssl)
set -euo pipefail
cd "$(dirname "$0")/.."
PROJECT=hms-drill
WORK=$(mktemp -d)
PORT=${DRILL_HTTPS_PORT:-18443}
BASE="https://localhost:$PORT/api/v1"
ADMIN=drill@hotel.local
PASS=Drill-Admin-2026
SPOOFED=203.0.113.77
compose() { docker compose -p "$PROJECT" --env-file "$WORK/.env" "$@"; }
cleanup() {
  if [ "${KEEP:-}" = 1 ]; then echo "kept: docker compose -p $PROJECT --env-file $WORK/.env ..."; return; fi
  compose down -v --remove-orphans >/dev/null 2>&1 || true
  docker run --rm -v "$WORK:/w" alpine:3 rm -rf /w/backups >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT
step() { printf '\n== %s\n' "$*"; }
pass() { printf '   PASS  %s\n' "$*"; }
die() { printf '   FAIL  %s\n' "$*" >&2; exit 1; }

cat > "$WORK/.env" <<EOF
POSTGRES_PASSWORD=$(openssl rand -hex 24)
HMS_DB_APP_PASSWORD=$(openssl rand -hex 24)
HMS_DATA_KEY=$(openssl rand -base64 32 | tr '+/' '-_')
HMS_SITE_ADDRESS=https://localhost
HMS_TLS=internal
HMS_HTTP_PORT=${DRILL_HTTP_PORT:-18080}
HMS_HTTPS_PORT=$PORT
BACKUP_HOST_DIR=$WORK/backups
BACKUP_INTERVAL_HOURS=24
HMS_WORKERS=2
EOF

step "Build and start the production stack"
compose up -d --build >/dev/null
for _ in $(seq 1 120); do
  curl -skf "$BASE/health" >/dev/null 2>&1 && break
  sleep 2
done
curl -skf "$BASE/health" >/dev/null || { compose logs migrate api | tail -40; die "API not healthy"; }
[ "$(docker inspect -f '{{.State.ExitCode}}' "$(compose ps -aq migrate)")" = 0 ] || die "migrate failed"
pass "migrate service completed, API healthy in production mode"

step "Database roles"
roles=$(compose exec -T db psql -U hms -d hms -Atc \
  "SELECT string_agg(rolname || ':' || rolsuper || ':' || rolbypassrls, ' ' ORDER BY rolname) FROM pg_roles WHERE rolname IN ('hms_app', 'hms_api')")
[ "$roles" = "hms_api:false:false hms_app:false:false" ] || die "unexpected roles: $roles"
api_conns=$(compose exec -T db psql -U hms -d hms -Atc "SELECT count(*) FROM pg_stat_activity WHERE usename = 'hms_api'")
[ "$api_conns" -gt 0 ] || die "the API does not use hms_api"
pass "API connected as hms_api (not superuser, no BYPASSRLS)"

step "First administrator (CLI, application role)"
compose exec -T -e HMS_ADMIN_PASSWORD="$PASS" api hms-entrypoint cli bootstrap --org "Drill Group" \
  --hotel "Drill Hotel" --code DRILL --admin-email "$ADMIN" --admin-name "Drill Admin" \
  --timezone Asia/Phnom_Penh --currency USD >/dev/null
pass "bootstrap"

JAR="$WORK/cookies"
me=$(curl -sk -c "$JAR" -H 'Content-Type: application/json' -H "X-Forwarded-For: $SPOOFED" \
  -d "{\"email\":\"$ADMIN\",\"password\":\"$PASS\"}" "$BASE/auth/login")
CSRF=$(jq -r .csrf_token <<<"$me")
HOTEL=$(jq -r '.hotels[0].id' <<<"$me")
[ "$HOTEL" != null ] || die "login failed: $me"
api() { # method path [json]
  curl -sk -b "$JAR" -c "$JAR" -X "$1" -H "X-CSRF-Token: $CSRF" -H 'Content-Type: application/json' \
    ${3:+-d "$3"} "$BASE$2"
}

step "Forwarded header from a client"
ip=$(api GET "/hotels/$HOTEL/login-events" | jq -r '.items[0].ip')
[ "$ip" != "$SPOOFED" ] || die "the client chose its own IP address ($ip)"
pass "login recorded from $ip, not the spoofed $SPOOFED"

wait_run() { # request id, kind -> prints the run JSON once finished
  # (a restore's safety backup carries the same request id, kind "backup")
  for _ in $(seq 1 150); do
    run=$(api GET "/hotels/$HOTEL/backups" 2>/dev/null \
      | jq -c --arg id "$1" --arg kind "$2" '.runs[]? | select(.request_id == $id and .kind == $kind)' 2>/dev/null || true)
    [ -n "$run" ] && { echo "$run"; return; }
    sleep 2
  done
  die "request $1 did not finish"
}

step "Backup from the API"
api POST "/hotels/$HOTEL/buildings" '{"code":"BEFORE","name":"Before the backup"}' >/dev/null
for _ in $(seq 1 30); do
  [ "$(api GET "/hotels/$HOTEL/backups" | jq -r .service.running)" = true ] && break
  sleep 2
done
req=$(api POST "/hotels/$HOTEL/backups" | jq -r .request_id)
[ "$req" != null ] || die "backup request refused"
run=$(wait_run "$req" backup)
[ "$(jq -r .status <<<"$run")" = ok ] || die "backup failed: $run"
FILE=$(jq -r .file <<<"$run")
meta=$(api GET "/hotels/$HOTEL/backups" | jq -c --arg f "$FILE" '.backups[] | select(.file == $f)')
[ "$(jq -r .restorable <<<"$meta")" = true ] || die "backup not restorable: $meta"
pass "backup $FILE ($(jq -r .bytes <<<"$meta") bytes, test restore of $(jq -r .verified_tables <<<"$meta") tables)"

step "Restore from the API"
api POST "/hotels/$HOTEL/buildings" '{"code":"AFTER","name":"After the backup"}' >/dev/null
code=$(api POST "/hotels/$HOTEL/backups/restore" "{\"file\":\"$FILE\",\"password\":\"wrong\",\"confirmation\":\"DRILL\"}" | jq -r .error.code)
[ "$code" = INVALID_CURRENT_PASSWORD ] || die "wrong password accepted ($code)"
req=$(api POST "/hotels/$HOTEL/backups/restore" "{\"file\":\"$FILE\",\"password\":\"$PASS\",\"confirmation\":\"drill\"}" | jq -r .request_id)
[ "$req" != null ] || die "restore request refused"
started=$(date +%s)
run=$(wait_run "$req" restore)
[ "$(jq -r .status <<<"$run")" = ok ] || die "restore failed: $run"
pass "restore finished in about $(( $(date +%s) - started )) s; safety backup $(jq -r .safety_backup <<<"$run")"

codes=$(api GET "/hotels/$HOTEL/buildings" | jq -r '[.[].code] | sort | join(",")')
[ "$codes" = BEFORE ] || die "data after restore: $codes (expected BEFORE only)"
pass "data is back to the backup (AFTER is gone)"
api GET "/hotels/$HOTEL/audit-logs?limit=200" | jq -e '.items | any(.action == "system.restore")' >/dev/null \
  || die "no system.restore entry in the audit trail"
pass "restore recorded in the audit trail"
api GET "/hotels/$HOTEL/backups" | jq -e '.backups | any(.trigger == "safety")' >/dev/null || die "no safety backup listed"
pass "safety backup listed"
status=$(curl -sk -o /dev/null -w '%{http_code}' -b "$JAR" -X POST -H "X-CSRF-Token: $CSRF" \
  -H 'Content-Type: application/json' -d '{"code":"AGAIN","name":"Written after the restore"}' "$BASE/hotels/$HOTEL/buildings")
[ "$status" = 201 ] || die "writing after the restore: HTTP $status"
pass "the running API writes to the restored database (HTTP 201), no restart"

step "Drill passed"
