# 5. Development Roadmap

Each phase ends with a working, tested application, and every test from
earlier phases must still pass. A feature counts as *done* only when it is
implemented, covered by automated tests, and documented. Live status is in
[`docs/CHECKLIST.md`](../CHECKLIST.md).

| Phase | Scope | Acceptance criteria |
|-------|-------|---------------------|
| **1. Architecture** | Requirements analysis, stack, architecture, DB model, API conventions, security model, OTA strategy, deployment strategy | The documents in `docs/architecture/` |
| **2. Foundation** | Monorepo, Docker Compose, FastAPI app, DB and migrations, error model, auth (sessions, CSRF, lockout), RBAC catalog + seeded roles, audit log, real-time hub, React app shell, design system, i18n in 5 languages, module-driven navigation, login, user language preference | Backend tests for auth/RBAC/audit/WS pass; the frontend builds and type-checks; a user can log in, switch language, and see only the menus they are allowed |
| **3. Hotel configuration** | Hotel profile, buildings, floors, room categories, amenities, rooms (bulk creation), facilities, services, taxes, currencies | CRUD + validation + permissions + audit tested; all screens translated |
| **4. Core management** | Guests (CRM, duplicate detection), inventory and allocation ledger, availability, rate plans, daily rates, pricing rules, `quote()`, reservations (create/modify/cancel, history), timeline calendar | Concurrency tests prove no double allocation; pricing tests cover seasons, weekends, long stays, taxes |
| **5. Operations** | Check-in/out, folio, payments (multi-currency), invoices/receipts (PDF in 5 languages), housekeeping, maintenance + room blocks | Balance math tested; gapless invoice numbering tested; Khmer PDF renders correctly |
| **6. Multi-user** | Session management UI, connected users, conflict UX, idempotency keys, reconnect behaviour | Multi-client WS tests; version-conflict tests |
| **7. Channel manager** | Adapter framework, job queue, mappings, ARI push, reservation import, reconciliation, dashboard; Booking.com and Agoda adapters to the extent official access allows | Adapter contract tests (against recorded *official* sample messages only); queue retry tests; no adapter is reported "operational" without a verified live test |
| **8. Analytics** | Dashboard KPIs (occupancy, ADR, RevPAR, cancellation rate, source mix), reports, exports | KPI formulas tested against fixtures |
| **9. Cross-platform** | Tauri shell (AppImage, DEB, EXE, portable), PWA manifest, tablet layouts, iPad Safari checks | Builds produced in CI; documented manual test matrix |
| **10. Final QA** | Security audit, RLS hardening, load tests, backup/restore drill, docs | Restore drill passes; load test report |

## Sequencing rationale

* Configuration (3) comes before reservations (4) because availability is
  derived from configured rooms; nothing in phase 4 may hardcode inventory.
* The allocation ledger, with its database constraint, is built *before* the
  calendar UI, so the UI is never the line of defence.
* Real-time infrastructure is built in phase 2, so every later module emits
  events from day one instead of being retrofitted in phase 6.
* The channel manager (7) comes after operations because its correctness
  depends on the inventory and pricing engines being final.

## API conventions (contract)

* Base path `/api/v1`. Hotel-scoped resources are under `/api/v1/hotels/{hotel_id}/…`.
* JSON in snake_case. Dates are ISO `YYYY-MM-DD`; timestamps are ISO-8601 UTC.
* Money is serialised as a **string** decimal (`"125.00"`) with a separate
  `currency`, never as a float.
* Lists are paginated with `?limit=&offset=` and return
  `{items, total, limit, offset}`.
* Errors are always
  `{"error": {"code": "ROOM_UNAVAILABLE", "message": "...", "params": {...}, "fields": [{"loc": [...], "code": "..."}]}}`.
  The `code` is stable and translated by the client; `message` is an English
  fallback for logs and scripts.
* Updates use `PATCH` with the current `version`, and a mismatch returns `409 VERSION_CONFLICT`.
* Creation endpoints honour `Idempotency-Key`.
* OpenAPI is served at `/api/docs` (disabled in production unless enabled by configuration).
