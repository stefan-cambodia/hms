#!/usr/bin/env bash
# Load test on a throwaway copy of the production stack (project "hms-load",
# own volumes and ports, removed at the end unless KEEP=1): Caddy + API
# (HMS_WORKERS processes) + PostgreSQL, exactly as installed in a hotel.
#
#   deploy/tests/load-test.sh [loadtest/run.py options, e.g. --staff 30 --minutes 5]
#
# Needs docker compose, curl, openssl and the backend's virtualenv
# (backend/.venv with httpx and websockets). Writes the JSON result and the
# containers' resource samples into deploy/tests/results/.
set -euo pipefail
cd "$(dirname "$0")/.."
PROJECT=hms-load
WORK=$(mktemp -d)
PORT=${LOAD_HTTPS_PORT:-19443}
ADMIN=load@hotel.local
PASS=Load-Admin-2026
OUT=tests/results
mkdir -p "$OUT"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
compose() { docker compose -p "$PROJECT" --env-file "$WORK/.env" "$@"; }
cleanup() {
  [ -n "${SAMPLER:-}" ] && kill "$SAMPLER" 2>/dev/null || true
  if [ "${KEEP:-}" = 1 ]; then echo "kept: docker compose -p $PROJECT --env-file $WORK/.env ..."; return; fi
  compose down -v --remove-orphans >/dev/null 2>&1 || true
  docker run --rm -v "$WORK:/w" alpine:3 rm -rf /w/backups >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT

cat > "$WORK/.env" <<EOF
POSTGRES_PASSWORD=$(openssl rand -hex 24)
HMS_DB_APP_PASSWORD=$(openssl rand -hex 24)
HMS_DATA_KEY=$(openssl rand -base64 32 | tr '+/' '-_')
HMS_SITE_ADDRESS=https://localhost
HMS_TLS=internal
HMS_HTTP_PORT=${LOAD_HTTP_PORT:-19080}
HMS_HTTPS_PORT=$PORT
BACKUP_HOST_DIR=$WORK/backups
BACKUP_INTERVAL_HOURS=24
HMS_WORKERS=${HMS_WORKERS:-2}
EOF

echo "== starting the production stack (HMS_WORKERS=${HMS_WORKERS:-2})"
compose up -d --build >/dev/null 2>&1
for _ in $(seq 1 120); do curl -skf "https://localhost:$PORT/api/v1/health" >/dev/null 2>&1 && break; sleep 2; done
compose exec -T -e HMS_ADMIN_PASSWORD="$PASS" api hms-entrypoint cli bootstrap --org "Load Group" \
  --hotel "Load Hotel" --code LOAD --admin-email "$ADMIN" --admin-name "Load Admin" \
  --timezone Asia/Phnom_Penh --currency USD >/dev/null

# Resource use of each container every 5 s while the test runs.
( while true; do
    docker stats --no-stream --format '{{.Name}},{{.CPUPerc}},{{.MemUsage}}' \
      $(compose ps -q) 2>/dev/null | sed "s/^/$(date -u +%H:%M:%S),/"
    sleep 5
  done ) > "$OUT/load-$STAMP-stats.csv" &
SAMPLER=$!

# The computer must not go to sleep during the measurement (a laptop's
# suspend shows up as multi-second "latencies"): inhibit it while it runs.
INHIBIT=()
command -v systemd-inhibit >/dev/null && INHIBIT=(systemd-inhibit --what=sleep:idle --who=hms-load-test --why="HMS load test")
"${INHIBIT[@]}" ../backend/.venv/bin/python ../backend/loadtest/run.py --base "https://localhost:$PORT" --insecure \
  --email "$ADMIN" --password "$PASS" --out "$OUT/load-$STAMP.json" "$@"
echo "== results: deploy/$OUT/load-$STAMP.json and load-$STAMP-stats.csv"
