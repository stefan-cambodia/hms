#!/bin/sh
set -eu
case "${1:-api}" in
  migrate)
    # Runs as the schema owner (HMS_MIGRATION_DATABASE_URL), once per start of
    # the stack, before the API. Migrations are transactional and idempotent.
    alembic upgrade head
    python -m app.cli db-roles
    python -m app.cli sync-roles
    ;;
  api)
    # The API only knows the least-privilege role (HMS_DATABASE_URL) and
    # refuses to start in production with a role that bypasses row-level security.
    # Only Caddy can reach this port (internal Docker network), so trusting
    # its X-Forwarded-* headers is safe.
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000 \
      --workers "${HMS_WORKERS:-2}" --proxy-headers --forwarded-allow-ips='*' \
      --no-server-header
    ;;
  cli)
    shift
    exec python -m app.cli "$@"
    ;;
  *)
    exec "$@"
    ;;
esac
