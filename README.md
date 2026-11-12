# HMS — Hotel Management System

A centralized, multi-user, multi-language hotel management platform (PMS).
One server and one PostgreSQL database are shared by every device in the
hotel: Linux and Windows desktops, Android tablets and iPads.

**Status: phases 1–3 of 10 delivered** (architecture, foundation, hotel
configuration). Reservations, front desk, housekeeping, billing, channel
manager and the desktop installers are not built yet. See
[docs/CHECKLIST.md](docs/CHECKLIST.md) for the exact, tested state of every
feature.

| | |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, PostgreSQL 17 |
| Frontend | React 19, TypeScript, Mantine 8, TanStack Query, i18next |
| Real-time | WebSockets fed by PostgreSQL LISTEN/NOTIFY (transactional events) |
| Languages | English, Français, 简体中文, Русский, ខ្មែរ |
| Deployment | Docker Compose: Caddy (TLS) + API + PostgreSQL + verified backups |

## Documentation

- Architecture: [overview](docs/architecture/01-architecture.md) ·
  [database](docs/architecture/02-database.md) ·
  [channel manager / Booking.com / Agoda](docs/architecture/03-channel-manager.md) ·
  [security](docs/architecture/04-security.md) ·
  [roadmap](docs/architecture/05-roadmap.md)
- [Installation & operations guide](docs/guides/installation.md): server, devices, backups, restore
- [OTA connectivity research](docs/research/ota-connectivity.md) (sourced)
- [Development checklist](docs/CHECKLIST.md)

## Development quick start

```bash
# 1. Database
docker compose -f docker-compose.dev.yml up -d

# 2. Backend (http://127.0.0.1:8000, API docs at /api/docs)
cd backend
python3.12 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/alembic upgrade head
HMS_ADMIN_PASSWORD='Choose-A-Strong-One-1' .venv/bin/python -m app.cli bootstrap \
  --org "My Group" --hotel "My Hotel" --code MYHOTEL \
  --admin-email admin@hotel.lan --admin-name "Administrator" \
  --timezone Asia/Phnom_Penh --currency USD
HMS_COOKIE_SECURE=false .venv/bin/uvicorn app.main:app --reload

# 3. Frontend (http://localhost:5173, proxies /api and the WebSocket)
cd frontend && npm ci && npm run dev
```

## Tests

```bash
cd backend  && .venv/bin/pytest            # 31 tests against real PostgreSQL (incl. live WebSocket tests)
cd frontend && npm test                    # unit tests
cd frontend && npm run i18n:check          # translation completeness in all 5 languages
cd frontend && npm run e2e                 # Playwright: desktop, iPad, Android tablet (needs running stack)
```

## Production

See the [installation guide](docs/guides/installation.md). In short:

```bash
cd deploy && cp .env.example .env   # set POSTGRES_PASSWORD, HMS_DATA_KEY, HMS_SITE_ADDRESS
docker compose up -d --build
docker compose exec api hms-entrypoint cli bootstrap --org ... --hotel ... --code ... \
  --admin-email ... --admin-name ...
```
