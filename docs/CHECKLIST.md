# Development Checklist

Legend: ✅ implemented **and** covered by automated tests · 🟡 implemented, partially tested or with a known limitation · ⬜ not started

Last updated: 2026-11-12. Test counts: backend 31 (pytest, real PostgreSQL), frontend unit 12 (Vitest), end-to-end 15 (Playwright on desktop, iPad landscape and Android tablet viewports; 4 are desktop-only by design).

## Phase 1 — Architecture ✅

| Item | Status | Where |
|------|--------|-------|
| Architecture, stack justification, module structure | ✅ | docs/architecture/01-architecture.md |
| Database model | ✅ | docs/architecture/02-database.md |
| Multi-device and offline strategy | ✅ | 01-architecture.md §1.5–1.6 |
| Booking.com / Agoda strategy, based on primary-source research | ✅ | 03-channel-manager.md, docs/research/ota-connectivity.md |
| Security strategy | ✅ | 04-security.md |
| Roadmap and API conventions | ✅ | 05-roadmap.md |

## Phase 2 — Foundation

| Item | Status | Notes |
|------|--------|-------|
| Monorepo, dev database, migrations (Alembic, upgrade and downgrade tested) | ✅ | |
| Uniform error model with stable codes, translated client-side | ✅ | |
| Authentication: Argon2id, opaque sessions, httpOnly cookie or bearer token | ✅ | test_auth.py |
| CSRF protection (per-session token) | ✅ | |
| Brute-force protection: per-IP rate limit and account lockout | ✅ | |
| Optional TOTP two-factor authentication (secret encrypted at rest) | ✅ | Recovery codes ⬜ |
| Session management: list, revoke (own and admin), idle and absolute expiry | ✅ | |
| Login history | ✅ | |
| RBAC: permission catalog, 8 seeded system roles, custom roles | ✅ | test_rbac.py |
| Anti-escalation (cannot grant permissions you lack) | ✅ | |
| Tenant isolation (composite FKs; 404 for foreign hotels) | ✅ | PostgreSQL RLS planned for phase 10 |
| Append-only audit log (DB trigger) with before/after diffs | ✅ | |
| Optimistic locking (version column plus client-supplied version) | ✅ | |
| Real-time sync: pg_notify on commit → WebSocket → query invalidation | ✅ | test_realtime.py, E2E sync test |
| WebSocket security: origin check, auth, per-permission filtering, revocation closes socket | ✅ | |
| Disconnect detection: heartbeat watchdog, offline banner, writes disabled, auto-resync | ✅ | E2E offline test |
| Frontend shell, navigation generated from implemented modules only | ✅ | |
| Design system (Mantine theme, typography, self-hosted fonts) | ✅ | |
| i18n infrastructure, 5 languages, per-user language stored server-side | ✅ | i18n check plus E2E |
| Translation completeness check (keys, variables, plurals) | ✅ | `npm run i18n:check` |
| Khmer rendering (shaping, line height) | ✅ | Screenshots verified; **native-speaker review of wording pending** |
| Login rate limiter is per process | 🟡 | DB lockout covers multi-process; documented |
| Least-privilege DB roles (separate migration and app users) | ⬜ | Phase 10 |

## Phase 3 — Hotel configuration

| Item | Status | Notes |
|------|--------|-------|
| Hotel profile: identity, address, GPS, contact, social links, policies, billing info | ✅ | |
| Time zone, currency, supported/default languages (validated against ISO data) | ✅ | |
| Buildings and floors | ✅ | |
| Room categories: unlimited, multilingual, occupancy rules, beds, prices, amenities, templates | ✅ | |
| Rooms: single and bulk creation, overrides, location, deactivate/delete | ✅ | |
| Amenities: 14 defaults translated in 5 languages, unlimited custom | ✅ | |
| Facilities: multilingual, opening hours, availability, pricing, conditions | ✅ | |
| Sellable services (independent of room categories) | ✅ | |
| Tax rates (percent / fixed per night / per person-night, inclusive/exclusive) | ✅ | Applied by the pricing engine in phase 4 |
| Photos and logo upload (media module) | ⬜ | Model designed; upload and re-encoding not built |
| Additional currencies and exchange rates | ⬜ | Phase 5 (with payments) |
| Multi-property: create additional hotels (super admin), hotel switcher | ✅ | |

## Phase 4 — Core hotel management ⬜

Guests/CRM, room allocation ledger (exclusion constraint), availability engine, rate plans and daily rates, pricing rules, `quote()`, reservations (create/modify/cancel/history), timeline calendar.

## Phase 5 — Operations ⬜

Check-in/out, folio, payments (multi-currency), invoices and receipts (PDF in 5 languages), housekeeping tasks, maintenance with room blocks.

## Phase 6 — Multi-user ✅ (largely delivered early) / ⬜ (remaining)

Delivered in phase 2: real-time sync, sessions, connected-users view, conflict detection and stale-edit warning, offline banner.
Remaining ⬜: `Idempotency-Key` on creation endpoints (needed for reservations), multi-process login throttling.

## Phase 7 — Channel manager ⬜

The adapter framework and SiteMinder pmsXchange adapter come first. **Booking.com direct is currently closed to new connectivity providers**, and Agoda direct requires Tech Partner status. See 03-channel-manager.md. No integration is reported as working until it has been verified against the provider.

## Phase 8 — Analytics ⬜

The dashboard currently shows configuration and room-readiness data only. Occupancy, ADR, RevPAR and revenue need reservations (phase 4).

## Phase 9 — Cross-platform

| Item | Status | Notes |
|------|--------|-------|
| Responsive layout: desktop, iPad landscape, Android tablet portrait | ✅ | Playwright viewports (Chrome engine) |
| PWA manifest and icon (add to home screen) | 🟡 | Manifest present; no offline service worker (by design, see §1.6) |
| Real Safari/WebKit validation on iPad | ⬜ | Needs a WebKit run or a physical device |
| Tauri desktop shell (AppImage, DEB, EXE, portable) | ⬜ | WebKitGTK 4.1 is not installed on the dev machine; to be built in CI |

## Phase 10 — Final QA / operations

| Item | Status | Notes |
|------|--------|-------|
| Production Docker Compose (Caddy TLS, API, PostgreSQL, backups) | ✅ | Built and run; HTTPS, headers, WSS verified manually |
| Automated backups, each verified by restoring into a scratch database | ✅ | backup-once.sh |
| Restore procedure with safety backup and checksum check | ✅ | Restore drill performed 2026-11-12 |
| Backup history and restore in the admin UI | ⬜ | Script-based today (`last-run.json`) |
| CI pipeline | 🟡 | Workflow written; not yet run on a CI host |
| Load tests, security audit, RLS | ⬜ | |
