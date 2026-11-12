#!/bin/sh
set -eu
case "${1:-api}" in
  api)
    # Schema migrations are idempotent and transactional; run them on start.
    alembic upgrade head
    python -m app.cli sync-roles
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
