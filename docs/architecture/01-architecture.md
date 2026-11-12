# 1. System Architecture

This document covers deliverables 1, 2, 4, 5 and 6 of the Phase 1 analysis:
the recommended architecture, technology choices, module structure,
multi-device communication strategy, and the offline / local-network strategy.

## 1.1 Overview

```
                ┌──────────────────────── Hotel LAN (or cloud VPC) ────────────────────────┐
                │                                                                           │
 Linux desktop ─┤  Tauri shell ──┐                                                          │
 Win desktop   ─┤  Tauri shell ──┤      HTTPS + WSS     ┌──────────┐    ┌────────────────┐  │
 Android tablet ┤  Browser/PWA ──┼────────────────────▶ │  Caddy   │──▶ │  api (FastAPI) │  │
 iPad (Safari) ─┤  Browser/PWA ──┘                      │ TLS, SPA │    │  REST + WS     │  │
                │                                       └──────────┘    └───────┬────────┘  │
                │                                                               │ SQL +     │
                │                                                               │ LISTEN/   │
                │                                       ┌────────────────┐      │ NOTIFY    │
                │                                       │ worker         │◀─────┤           │
                │                                       │ jobs, channel  │      ▼           │
                │                                       │ sync, backups, │  ┌───────────┐   │
                │                                       │ email/SMS      │─▶│PostgreSQL │   │
                │                                       └───────┬────────┘  │    17     │   │
                │                                               │           └───────────┘   │
                └───────────────────────────────────────────────┼───────────────────────────┘
                                                                │ Internet (optional, may drop)
                              SiteMinder (→ Booking.com, Agoda) / SMTP / SMS
```

One central server (a Docker Compose stack) holds the only database. Every
device — desktop, tablet, iPad — is a client of that server. No device keeps an
independent database.

| Process  | Responsibility |
|----------|----------------|
| `caddy`  | TLS termination (internal CA on LAN, Let's Encrypt in the cloud), serves the built SPA, proxies `/api` and `/ws`. |
| `api`    | FastAPI application: REST API, WebSocket hub, authentication, all business rules. Stateless, so it can run several workers. |
| `worker` | Same codebase, different entrypoint: executes the durable job queue (channel sync, outbound email/SMS, scheduled backups, nightly tasks). |
| `db`     | PostgreSQL 17: the system of record, the job queue, and the event bus (LISTEN/NOTIFY). |

There is deliberately **no Redis / RabbitMQ**. A hotel server is often a single
small machine maintained by non-specialists; every extra stateful service is
another thing to back up and repair. PostgreSQL covers all three roles at hotel
scale (tens to low hundreds of concurrent users), and keeping jobs in the same
database lets a job be enqueued *in the same transaction* as the business
change that caused it. That is the basis of the "never silently discard"
guarantee in §1.6.

## 1.2 Technology stack and justification

| Layer | Choice | Why |
|-------|--------|-----|
| Backend language | Python 3.12 | Requested stack, mature ecosystem for PDF/i18n/XML (OTA messages are XML). 3.12 is the newest version with universal wheel coverage for every dependency used here. |
| Web framework | FastAPI + Pydantic v2 | Typed request/response contracts generate the OpenAPI document that serves as the API contract; native async WebSockets. |
| ORM / migrations | SQLAlchemy 2.0 (async, asyncpg) + Alembic | Explicit transactions and `SELECT … FOR UPDATE`; Alembic for versioned, reviewable migrations. Relationships default to `lazy="raise"` so no hidden queries. |
| Database | PostgreSQL 17 | `daterange` + `btree_gist` exclusion constraints make double-allocation of a room impossible at the database level; `pg_trgm` for fuzzy guest search; `SKIP LOCKED` for the job queue; LISTEN/NOTIFY for real-time fan-out. |
| Password hashing | Argon2id (`argon2-cffi`) | Current OWASP recommendation. |
| PDF | WeasyPrint | HTML/CSS templates (reusable, translatable) and HarfBuzz text shaping, which **Khmer requires**: ReportLab cannot shape Khmer clusters correctly. |
| Frontend | React 19 + TypeScript + Vite | Requested; Vite gives fast builds and a static bundle that Caddy and Tauri can both serve. |
| UI library | Mantine 8 | Complete professional component set (tables, date pickers, forms, modals, notifications, charts), good touch targets and accessibility, theming via CSS variables. Avoids hand-building dozens of primitives. |
| Server state | TanStack Query | Caching, background refetch, and targeted invalidation when a WebSocket event arrives. |
| Routing | React Router 7 | Standard; supports lazy-loaded routes per module. |
| i18n | i18next + react-i18next, `Intl.*` for formatting | Namespaced JSON catalogs, plurals for all five languages (including Russian's three plural forms), and lazy loading. |
| Fonts | Self-hosted via `@fontsource` — Inter (Latin/Cyrillic), Noto Sans SC, Noto Sans Khmer | **No CDN**: the hotel LAN must work with the Internet down. Unicode-range subsetting keeps the Chinese font cheap. |
| Desktop | Tauri 2 (thin shell) | Small native installers (AppImage, DEB, NSIS EXE) on the system WebView; see §1.4. |
| Reverse proxy | Caddy 2 | Automatic HTTPS (ACME in the cloud, `tls internal` on a LAN) with a three-line config, which suits non-specialist operators. |
| Packaging | Docker Compose | One-command install and upgrade on any Linux server, whether in the hotel or in the cloud. |
| Tests | pytest + httpx (backend, against real PostgreSQL), Vitest + Testing Library (frontend), Playwright (end-to-end) | Integrity rules live in the database, so backend tests never mock it. |

### Alternatives considered

* **Electron instead of Tauri** — rejected: 10× larger installers, and it brings
  nothing a thin client needs.
* **Bundling the SPA inside each desktop installer** — rejected as the default:
  every desktop would need upgrading in lockstep with the server, and version
  skew between clients and server is a real source of PMS data bugs. See §1.4.
* **Redis for pub/sub and queues** — rejected for the reasons in §1.1.
  The job and event interfaces are abstracted, so a broker can be added later
  if a multi-hotel cloud deployment outgrows PostgreSQL.
* **Microservices** — rejected. One hotel's workload fits comfortably in a
  modular monolith; module boundaries are enforced in code (§1.3) so a module
  can be extracted later if needed.

## 1.3 Application module structure

The backend is a **modular monolith**. Each module owns its models, schemas,
service (business logic) and router. Routers are thin: they validate input,
call a service, and serialise output. **Business rules exist only in
services**, never in routers, the frontend, or a second copy for another
platform.

```
backend/app/
  core/            config, database session, errors, security primitives,
                   permissions catalog, audit, events, money, i18n, pagination
  modules/
    auth/          login, sessions, 2FA, CSRF, password policy
    users/         users, roles, permissions, hotel access
    hotels/        organisation, hotel profile, buildings, floors, settings
    rooms/         room types (categories), rooms, amenities, room blocks
    facilities/    facilities and sellable services
    taxes/         tax rates, currencies, exchange rates
    guests/        CRM, duplicate detection, merge
    inventory/     availability computation, allocation ledger, locking
    pricing/       rate plans, daily rates, restrictions, pricing rules
    reservations/  reservation lifecycle, stays, history
    frontdesk/     check-in / check-out orchestration
    housekeeping/  room status, cleaning tasks
    maintenance/   maintenance requests, out-of-order blocks
    billing/       folios, payments, invoices, receipts, PDF
    channels/      channel manager core + adapters/ (booking_com, agoda)
    notifications/ in-app, email, SMS, WhatsApp dispatch
    reports/       dashboard KPIs, occupancy, revenue, ADR, RevPAR
    backups/       backup runs, verification, restore
    realtime/      WebSocket hub, LISTEN/NOTIFY bridge
    jobs/          durable job queue and worker
```

Dependency rule: modules may call another module's **service** functions, never
its tables directly. For example, `reservations` asks `inventory` for
availability and `pricing` for a quote, so each calculation lives in exactly
one place.

The frontend mirrors the same modules under `frontend/src/modules/*`, each
exporting its routes, navigation entry, and translations namespace. The
navigation is generated from a module registry, so **a menu entry only exists
once its module is implemented** (no dead menus).

### Multi-property (tenant) model

`organization` → many `hotel`s. Every hotel-owned row carries `hotel_id`.
Every hotel-scoped endpoint lives under `/api/v1/hotels/{hotel_id}/…`, and a
single dependency (`HotelContext`) verifies that the user holds a role in that
hotel before any query runs; repositories always filter by the context's
`hotel_id`. Cross-hotel access returns `404` (not `403`) so IDs from other
hotels can't be probed. PostgreSQL Row-Level Security is planned as
defence-in-depth in Phase 10. The UI hides the hotel switcher while an
organisation has a single hotel.

## 1.4 Cross-platform delivery

One React codebase serves every platform:

| Platform | Delivery |
|----------|----------|
| Linux (Ubuntu, Debian, Mint) | Tauri 2 shell → `.AppImage` and `.deb` |
| Windows 10/11 | Tauri 2 shell → NSIS `.exe` installer; portable `.exe` (WebView2 is preinstalled on Windows 10 21H2+ and 11) |
| Android tablets | Browser + installable PWA (manifest, icons, landscape and portrait, touch-sized targets) |
| iPad | Safari + "Add to Home Screen" PWA |

**Desktop shell design.** The Tauri app ships a small bundled *connection
screen* (choose and remember the server URL, test it, show its certificate
status). Once connected, the window loads the SPA **from the hotel server**. Consequences:

* Every device always runs exactly the UI version that matches the server's
  API, so there is no client/server version skew.
* Upgrading the server upgrades every client, which covers the
  "administrator-managed updates" requirement. The shell itself rarely
  changes, and is updated through Tauri's updater or a new installer.
* Auth uses one mechanism everywhere (same-origin httpOnly cookie).
* The shell adds native window and icon, desktop shortcut, single-instance
  behaviour, printing (system print dialog), and saving PDFs to disk.

If the server is unreachable, the shell shows its bundled connection screen
with automatic retry instead of a blank window.

## 1.5 Multi-device communication strategy

**Request path.** REST over HTTPS for every read and write. Each write runs in
a single database transaction inside a service function.

**Concurrency control.**

1. *Physical room allocation* — enforced by a PostgreSQL **exclusion
   constraint** on the `room_allocations` ledger
   (`EXCLUDE USING gist (room_id WITH =, period WITH &&)`). Reservation stays and
   out-of-order blocks both write to this ledger through triggers, so no code
   path (API, worker, OTA import, manual SQL) can put two occupancies on one
   room for overlapping nights. The API maps the violation (`23P01`) to
   `409 ROOM_UNAVAILABLE`.
2. *Room-type (unassigned) inventory* — when a booking holds a room type but no
   specific room yet, the service takes a transaction-scoped advisory lock per
   `(hotel, room_type)` (ordered by ID to prevent deadlocks), recomputes
   availability for the affected nights, and rejects if any night would go
   negative. Reservations arriving from an OTA can't be rejected (the guest
   already booked there), so they are accepted with an `overbooked` flag and
   an alert.
3. *Optimistic locking* — every mutable aggregate has a `version` column. The
   client sends the version it edited; a mismatch returns
   `409 VERSION_CONFLICT` with the current record, so an older edit never
   silently overwrites a newer one.
4. *Idempotency* — creation endpoints accept an `Idempotency-Key` header, so a
   retried request after a network blip can't create a duplicate reservation.

**Real-time synchronisation.**

```
service tx ──INSERT/UPDATE──▶ PostgreSQL ──(on COMMIT)──▶ NOTIFY hms_events
                                                              │
                         every api process LISTENs ◀──────────┘
                                   │ filter by hotel + permission
                                   ▼
                         WebSocket clients ──▶ TanStack Query invalidation ──▶ refetch
```

* `pg_notify` is transactional: an event is delivered **only if the
  transaction commits**, so clients never see changes that were rolled back.
* Events are small (`{hotel_id, entity, id, action, version, actor}`). Clients
  refetch through the normal permission-checked REST API rather than trusting
  pushed data, which keeps the event channel free of sensitive payloads.
* Every `api` process runs one LISTEN connection, so the design scales
  horizontally without a broker.
* The client reconnects with exponential backoff and jitter; **after any
  reconnect it invalidates all cached queries**, so events missed while
  disconnected cannot leave a stale screen.
* The WebSocket authenticates with the same session cookie, and the session
  is re-checked periodically, so revoking a session also closes its socket.

## 1.6 Offline and local-network strategy

The design separates two different failures.

### A. Internet outage (the common case) — fully supported

With the server **installed in the hotel** (recommended), staff devices talk to
it over the LAN. Losing the Internet affects only the external integrations:

| Keeps working | Waits for the Internet, then resumes automatically |
|---------------|-----------------------------------------------------|
| Reservations, rooms, guests, check-in/out, payments, housekeeping, maintenance, local reports, printing invoices and PDFs | Booking.com / Agoda sync, outbound email / SMS / WhatsApp, off-site backup copies |

Every outbound operation is a row in the `jobs` table, written **in the same
transaction** as the change that caused it (transactional outbox). Jobs retry
with exponential backoff and a cap; after `max_attempts` they move to `dead`
and raise an alert on the Channel Manager dashboard. They are never dropped.

**Channel jobs carry date ranges, not values.** A change marks "room type X,
nights A→B" as dirty; the worker computes availability and rates *at execution
time*, then sends only the values that differ from what the channel last
acknowledged (providers such as SiteMinder require delta-only updates). A job
that runs late therefore sends current data, never a stale snapshot, and
overlapping dirty ranges are coalesced. See
[03-channel-manager.md](03-channel-manager.md).

On reconnection the channel worker also runs **reconciliation**: it pulls any
reservations created on the OTAs during the outage (idempotent on
`(connection, external_id, revision)`), and those imports get the same
overbooking handling as any OTA booking. The dashboard always shows
*local availability* and *last confirmed channel availability* side by side,
with the time of the last successful push.

### B. A device loses its connection to the server

The central database is the only source of truth, so a disconnected device
**does not accept inventory-changing writes** (reservations, assignments,
check-ins, payments). Queuing those offline would recreate the double-booking
problem that the central design exists to prevent. Instead:

* a persistent banner shows "Disconnected — reconnecting…" with a retry
  countdown;
* screens already loaded stay readable (cached queries), clearly marked as
  possibly stale;
* forms keep their unsaved input, and submitting is disabled until the
  connection returns;
* on reconnect, all queries refetch.

### C. Deployment choice and resilience

| Deployment | Internet outage | Notes |
|------------|-----------------|-------|
| Server inside the hotel (dedicated machine or LAN server) | Operations continue | **Recommended.** Backups are copied off-site automatically once the link is back. |
| Cloud server | Operations stop until the link returns | Simplest to run. Suitable for hotels with a reliable connection plus a 4G fallback router. |

All three supported deployment targets (dedicated machine, LAN server, cloud)
use the same Compose stack; only the Caddy TLS mode and the backup
destination differ.
