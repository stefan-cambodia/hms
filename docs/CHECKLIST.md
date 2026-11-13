# Development Checklist

Legend: ✅ implemented **and** covered by automated tests · 🟡 implemented, partially tested or with a known limitation · ⬜ not started

Last updated: 2026-11-13. Test counts: backend 163 passed + 1 opt-in live test skipped (pytest, real PostgreSQL, run as the least-privilege role), frontend unit 38 (Vitest), end-to-end 54 passed and 36 skipped by design across desktop, iPad landscape and Android tablet locally (Playwright), plus iPad Safari (WebKit) in CI. Restore drill and load test on the production stack: see docs/qa/phase10-report.md.

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
| Optional TOTP two-factor authentication (secret encrypted at rest) | ✅ | Administrator reset for a lost phone (phase 10, ends the user's sessions, audited). Recovery codes and mandatory 2FA per role ⬜ |
| Session management: list, revoke (own and admin), idle and absolute expiry | ✅ | |
| Login history | ✅ | |
| RBAC: permission catalog, 8 seeded system roles, custom roles | ✅ | test_rbac.py |
| Anti-escalation (cannot grant permissions you lack) | ✅ | |
| Tenant isolation (composite FKs; 404 for foreign hotels) | ✅ | Enforced by PostgreSQL row-level security since phase 10 |
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
| Login throttling per IP shared by all API processes (PostgreSQL counters) | ✅ | test_auth; account lockout on top |
| Least-privilege DB roles (separate migration and app users) | ✅ | Phase 10: API as `hms_api` (member of `hms_app`), migrations in the `migrate` service |

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
| Photos and logo upload (media module) | ✅ | Logo (application header, invoices, receipts, folios, restaurant bills, rental contracts, day reports; issued invoices keep their logo) and photos of room categories and facilities (order, viewer, delete). Type checked from the content, re-encoded without EXIF/GPS, stored in PostgreSQL so backups include them. `test_media.py`, E2E `media.spec.ts` |
| Additional currencies and exchange rates | ✅ | Phase 5: Configuration → Currencies |
| Multi-property: create additional hotels (super admin), hotel switcher | ✅ | |

## Phase 4 — Core hotel management ✅

| Item | Status | Notes |
|------|--------|-------|
| Room allocation ledger maintained by triggers, with a deferrable exclusion constraint | ✅ | Overlap rejected even by raw SQL (test) |
| No double allocation under concurrency (10 parallel bookings of one room → exactly 1) | ✅ | test_reservations.py |
| No category oversell under concurrency (advisory locks + post-check) | ✅ | 6 racing bookings for 2 rooms → 2 succeed |
| Explicit, flagged overbooking (`reservations.overbook` permission only) | ✅ | |
| Availability per category and night (`/availability`) | ✅ | |
| Room blocks (out of service) removing rooms from sale | ✅ | Conflicts with stays and overselling refused |
| Reservations: create (new or existing guest), quote, list/search, detail | ✅ | |
| Modify: details, room assignment/reassignment, date changes (booked nights keep their price) | ✅ | |
| Status state machine: confirm, cancel (releases inventory), no-show (not before arrival) | ✅ | Check-in/out endpoints come in phase 5 |
| Reservation history (events) and `is_modified` badge | ✅ | |
| Idempotency-Key on creation (sequential and concurrent retries) | ✅ | |
| Occupancy limits per category/room | ✅ | |
| Price quote: base price, occupancy supplements, taxes (percent / per night / per person-night, inclusive/exclusive) | ✅ | |
| Rate plans: meal plans, refundable/non-refundable, cancellation policy, categories, validity, booking window, default plan | ✅ | test_pricing.py |
| Derived plans (percent, amount, amount per person) with restriction inheritance | ✅ | |
| Seasons/special events, weekday/weekend, occupancy-based pricing | ✅ | |
| Long-stay, last-minute, early-bird discounts | ✅ | |
| Restrictions: min/max stay, stop sell, closed to arrival/departure, enforced with audited override permission | ✅ | |
| Rate calendar (plan × category × day) with bulk edit: set/±%/±amount/back to automatic, weekdays, restrictions | ✅ | API tests + E2E |
| Offers: every applicable plan with stay total and restriction warnings (reservation form, reservation page) | ✅ | |
| Change a stay's rate plan (reprices), date changes price new nights with the stay's plan | ✅ | |
| Cancellation policies (free-cancellation deadline shown on reservations) | ✅ | Fee charging comes with folios (phase 5) |
| Channel-specific rate mapping | ✅ | Phase 7: room and rate codes per connection |
| Guests: CRUD, fuzzy search (pg_trgm), duplicate detection, encrypted ID documents (audited reads) | ✅ | Guest merge ⬜ |
| Calendar data endpoint (stays, blocks, unassigned, availability) | ✅ | |
| Reservations list: quick filters (arrivals/departures today, in house, pending), search, status filter | ✅ | E2E |
| New reservation: guest search or creation with live duplicate warning, multi-room, live availability per category, free rooms, live price quote, Idempotency-Key, explicit overbooking confirmation | ✅ | E2E |
| Reservation detail: confirm, cancel (reason), no-show, edit details, assign/reassign room, change dates, nightly prices, totals, history with staff names | ✅ | E2E |
| Timeline calendar: rooms × days, category groups with availability (red when oversold), unassigned lanes, blocks, today/weekend shading, week/2 weeks/month, category filter, guest search, URL-shareable view | ✅ | E2E + unit (layout) |
| Calendar booking from an empty cell; quick view drawer | ✅ | E2E |
| Drag & drop (room and/or dates, atomic `move`, confirmation, edge auto-scroll); long-press on tablets | ✅ | E2E: mouse (desktop) + touch via CDP (Android tablet) |
| Room blocks from the calendar (create/remove) | ✅ | API tests; UI manual |
| Guests screens: search, profile edit, identity documents (permission-gated), stay history | ✅ | API tests; UI manual |
| Day view / category-only grouping toggle | ⬜ | Week/2 weeks/month ranges and category filter cover current needs |
| Dashboard KPIs from reservations (arrivals, departures, occupancy) | ✅ | Phase 8 |
| Multi-room reservations with different dates per room | 🟡 | Supported by the API; covered by the single-room tests only |

## Phase 5 — Operations ✅

### Front desk and billing ✅

| Item | Status | Notes |
|------|--------|-------|
| Check-in: from arrival date (late arrivals allowed), room must be assigned, previous guest must have left, dirty room needs explicit confirmation | ✅ | test_frontdesk.py |
| Walk-in (new reservation prefilled for tonight, source walk-in), pending reservations can be checked in | ✅ | |
| Undo check-in (same hotel day) | ✅ | |
| Check-out: balance must be settled (open balance needs folio.adjust; credit needs confirmation), room becomes dirty | ✅ | |
| Early departure releases the unused nights (inventory and bill) after explicit confirmation | ✅ | |
| In-house room move: stay split at today, booked prices kept, old room dirty, availability checked | ✅ | |
| Front desk page: arrivals (late arrivals flagged), in house (overdue flagged), departures, balances, planning view for other days | ✅ | E2E |
| Room board: occupancy, arrival today, out of service, cleaning status with quick change (housekeeping.update) | ✅ | E2E (3 devices) |
| Folio: accommodation from fixed nightly prices, service charges (catalog or free text, service taxes), fees, adjustments (folio.adjust), voids with reason | ✅ | Balance math tested |
| Payments: payment / deposit / refund, 5 methods, card brand + last 4 only, references; idempotent; concurrent postings serialised | ✅ | |
| Multi-currency payments: accepted currencies with rates, rate stored per payment, stale-rate protection (EXCHANGE_RATE_CHANGED) | ✅ | |
| Refunds limited to the amount paid; refund/void permissions enforced | ✅ | |
| Card-number guard on free-text fields (payments, charges, reservation and guest notes) | ✅ | Luhn-checked |
| Financial records append-only (DB trigger: no delete, only voiding, no un-voiding) | ✅ | |
| Invoices: gapless numbers (concurrency + rollback tested), one active per reservation, immutable snapshot, void and reissue, bill to guest or company | ✅ | |
| Receipts per payment (gapless numbers) and guest folio statement | ✅ | |
| PDFs in 5 languages (WeasyPrint + HarfBuzz; Noto fonts) — Khmer and Chinese verified visually and by embedded fonts | ✅ | Also verified inside the Docker image |
| Cancellation fees from the policy (free window, nights/percent, non-refundable), no-show fees; preview; waive needs folio.adjust | ✅ | |
| Payments & invoices page: cash-up totals per method/currency, net received, invoice search, void | ✅ | E2E |
| City-ledger / company accounts, split folios, credit notes | ⬜ | Invoices are corrected by void + reissue |
| End-of-day closure (night audit): open items (expected not arrived, due out not departed, open checks, overdue rentals, next day without room, balances due), no-show from the list, day report with cash-up, closure record + PDF, closed days frozen | ✅ | `test_nightaudit.py`, E2E `night-audit.spec.ts`. Run after midnight, days in order. No-shows are confirmed by the auditor, not automatic. No daily room revenue posting: accommodation is billed from fixed nightly prices |
| Payment terminal / online payment gateway integration | ⬜ | Card payments are recorded, not processed |

### Housekeeping and maintenance ✅

| Item | Status | Notes |
|------|--------|-------|
| Cleaning tasks: departure, stayover, deep clean, touch-up, inspection; priorities; notes | ✅ | test_housekeeping.py |
| Daily preparation from the rooms' situation (idempotent; out-of-service rooms skipped; urgent when a guest arrives today) | ✅ | |
| Automatic departure clean on check-out and room move; pending stayover dropped when the guest leaves | ✅ | |
| Workflow: start → done → inspected, reject (redo, reason), skip (reason), reopen; room cleaning status follows | ✅ | |
| Permissions: housekeepers act on their own or unassigned tasks; supervisors plan, assign, inspect | ✅ | New system role "Housekeeping supervisor" |
| Assignment (single and bulk) only to housekeeping staff of the hotel | ✅ | |
| Room cleaning-status history (who, when, why) | ✅ | |
| Housekeeping page: today's tasks (filters, bulk assign), "My tasks" (tablet-friendly, report a problem), room board | ✅ | E2E (3 devices) |
| Maintenance requests: room / facility / location, category, priority, numbering, assignment to technicians, comments, history | ✅ | |
| Workflow: reported → in progress ⇄ on hold → completed / cancelled, reopen | ✅ | |
| Out of service through room blocks (refused if a guest occupies the room), change dates, back in service keeping past nights | ✅ | |
| Completion releases the room from tonight and sends housekeeping (touch-up task) | ✅ | E2E |
| Room board: open repairs and today's task per room (front desk and housekeeping) | ✅ | |
| Photos on maintenance requests | ✅ | Attached when reporting the problem (tablet camera or gallery) or later; reporters remove their own photos, maintenance managers any; shown only with `maintenance.view`. `test_media.py`, E2E `media.spec.ts` |
| Recurring / preventive maintenance schedules, spare parts | ⬜ | |
| Lost & found, minibar counts by housekeeping | ⬜ | Minibar can be charged from the folio |

## Restaurant & bar (added on request) ✅

| Item | Status | Notes |
|------|--------|-------|
| Outlets (restaurant, bar, café, room service) with service charge; module hidden when the hotel has none | ✅ | test_restaurant.py |
| Menu: categories, multilingual items, prices, preparation station, sold-out switch (kitchen) | ✅ | |
| Tables with areas and seats; one open check per table (DB index); move a check to another table | ✅ | |
| Checks: dine-in, takeaway, room service (in-house guest); names and prices frozen when ordered; repeated taps add to the unsent line | ✅ | |
| Send to kitchen/bar; kitchen display (station filter, waiting time); preparing → ready → served | ✅ | E2E |
| Void sent items and payments (reason + restaurant.void), discounts (% or amount, reason), cancel checks | ✅ | |
| Totals: service charge, food & beverage taxes (inclusive/exclusive) | ✅ | |
| Payment: cash with change, card (brand + last 4), transfer, other; foreign currencies at the configured rate; split payments; auto-close when paid; void reopens | ✅ | |
| Charge to room: whole check to an in-house guest's folio with its tax lines; voidable only from the check | ✅ | E2E |
| Bill and receipt PDFs in 5 languages | ✅ | |
| Breakfast list (rates with breakfast / half / full board / all inclusive) with served covers | ✅ | |
| Sales report: totals, covers, average check, by category, best sellers, by payment method, voids | ✅ | |
| Stock / recipes / purchasing | ⬜ | Not included |
| Table reservations, kitchen printers, online ordering | ⬜ | Not included |

## Vehicle rental (added on request) ✅

| Item | Status | Notes |
|------|--------|-------|
| Fleet: scooters, motorbikes, cars, vans, bicycles, e-bikes, tuk-tuks, boats; rates per day/hour, driver, deposit; odometer; status; insurance and registration expiry with warnings | ✅ | test_vehicles.py |
| Module hidden when the hotel has no vehicles (managers can set it up) | ✅ | |
| Bookings by the hour for in-house guests or other customers (CRM guest created on the fly); availability per period | ✅ | |
| No double booking: database exclusion constraint (concurrency and raw SQL tested) | ✅ | |
| Price fixed when booked; change of return time reprices; late return fee with 59-minute grace | ✅ | |
| Hand-over: licence (encrypted, last 4 shown), odometer, fuel, condition, deposit (cash, card guarantee, passport/ID held); early hand-over starts the rental | ✅ | |
| Return: odometer, fuel, condition, fuel and damage charges, deposit given back, send vehicle to maintenance; waiving late fee needs a manager | ✅ | |
| Safety: no rental with expired insurance/registration, vehicle in maintenance, or still out with a previous renter | ✅ | |
| Payment: cash with change, card, transfer, currencies; charge to room after return; voids; discounts | ✅ | Shared with the restaurant (billing/pos.py) |
| Rental contract PDF in 5 languages with terms and signature lines | ✅ | Khmer checked visually |
| Today board (to hand over, out, due back, coming), 14-day schedule, fleet management | ✅ | E2E on 3 devices |
| Photos of damage, GPS tracking, online booking by guests | ⬜ | Not included |

## Phase 6 — Multi-user ✅

Delivered in phase 2: real-time sync, sessions, connected-users view, conflict detection and stale-edit warning, offline banner.
Delivered later: `Idempotency-Key` on reservation, payment, restaurant and rental creation (retries never create duplicates); login throttling shared by all API processes.

## Phase 7 — Channel manager 🟡 (core ✅, SiteMinder adapter awaiting live verification)

**Booking.com direct is currently closed to new connectivity providers**, and Agoda direct requires Tech Partner status (see 03-channel-manager.md). The route is SiteMinder pmsXchange. No integration is reported as working until it has been verified against the provider.

| Item | Status | Notes |
|------|--------|-------|
| Connections (encrypted credentials, test/production, pause), status shown to staff | ✅ | test_channels |
| Change queue written by database triggers (reservations, room assignments, blocks, rooms, rates, plans, rules, taxes) | ✅ | Bulk rate changes produce one range per category |
| Delta-only ARI: availability (room level), restrictions and PDP rates (room-rate level), merged ranges, plan conditions as stop sell | ✅ | First sync = horizon; then only changes |
| Worker: single leader, one request at a time per property, backoff on failure, horizon extended daily, full refresh at most once per 24 h | ✅ | |
| Reservation import: idempotent, out of order, never refused (overbooking flagged), channel prices and taxes, in-place modification, cancellation without fee | ✅ | |
| Acknowledgement after local commit; failures reported to the provider; retry after fixing the mapping | ✅ | |
| Card data never stored (brand + last 4 only); message log redacted | ✅ | Tested with SiteMinder's sample containing a card |
| Screens: connection, mapping (codes fetched from the provider), received bookings, activity log | ✅ | E2E on 3 devices; the E2E never calls the provider |
| SiteMinder adapter: messages match the official samples; HTTP exchange end to end | ✅ | tests/fixtures/siteminder |
| SiteMinder adapter: live check against the public test environment | ⬜ | `tests/test_siteminder_live.py`, not run yet (see 03-channel-manager.md §3.5) |
| SiteMinder: reservation pull verified with a partner test account; certification | ⬜ | Needs a partnership agreement |
| OBP rates, reservation push delivery, virtual cards | ⬜ | Not implemented |
| Booking.com / Agoda direct adapters | ⬜ | Need partner access |

## Phase 8 — Analytics ✅

Definitions: [`docs/guides/reports.md`](guides/reports.md). The formulas live in one place, `app/modules/reports/service.py`.

| Item | Status | Notes |
|------|--------|-------|
| KPIs: occupancy, ADR, RevPAR, room revenue, room nights, out of service | ✅ | test_reports: values computed by hand on a fixture hotel |
| Bookings: cancellation rate (booking basis), no-show rate, average stay, lead time | ✅ | |
| Breakdowns by source, room type, rate plan; revenue by department without double counting room charges | ✅ | Restaurant and rental charges to a room counted once |
| Comparison with the previous period or the same period last year (29 February handled) | ✅ | |
| Forecast on the books (30–180 days) with 7-day pickup | ✅ | |
| Dashboard: tonight, arrivals, departures, in house, month to date vs last year, next 14 nights | ✅ | E2E on 3 devices |
| Revenue figures only with `reports.financial`; ratios null (not 0) when there is nothing to divide | ✅ | |
| CSV exports readable by Excel in every language (BOM, `;` and decimal comma where the locale uses them, formula injection neutralised) | ✅ | Unit tests |
| Charts: one axis, accessible (keyboard, table view, legend), colours checked for colour blindness in light and dark mode | ✅ | |
| Historic room count (rooms taken out of service permanently) | 🟡 | Rooms count from their creation (or from an earlier night on which they were sold); deactivation history is not kept, so a deactivated room disappears from past periods too |
| PDF reports, scheduled e-mail reports | 🟡 | End-of-day report as PDF (night audit); performance reports export CSV only; no e-mail |

## Phase 9 — Cross-platform ✅ (installers built in CI; physical devices to try)

| Item | Status | Notes |
|------|--------|-------|
| Responsive layout: desktop, iPad landscape, Android tablet portrait | ✅ | Playwright viewports |
| iPad with Safari's engine (WebKit) | ✅ | Playwright WebKit project, run in the E2E workflow on Ubuntu (this distribution lacks WebKit's system libraries) |
| End-to-end tests in CI on a fresh installation (`hms seed-demo` demo hotel) | ✅ | `.github/workflows/e2e.yml`: desktop, iPad, Android tablet, iPad Safari |
| PWA: manifest, PNG and maskable icons, apple-touch-icon, standalone mode | ✅ | E2E `pwa.spec.ts`; no offline service worker (by design, §1.6) |
| Desktop shell (Tauri 2): connection screen (5 languages), certificate diagnosis, navigation limited to the hotel server, documents in their own window, PDFs saved and opened, single instance, menu | ✅ | Logic unit-tested (`desktop/core`), clippy clean, compiled against the Windows target locally |
| Installers: AppImage, DEB (Ubuntu 22.04 build), NSIS installer and portable EXE | 🟡 | Built by `.github/workflows/desktop.yml`; to be tried on real Linux and Windows computers |
| Physical iPad and Android tablet check | ⬜ | Manual |
| Code signing, shell auto-update | ⬜ | Needs a code-signing certificate |

## Phase 10 — Final QA / operations

| Item | Status | Notes |
|------|--------|-------|
| Production Docker Compose (Caddy TLS, API, PostgreSQL, migrations, backups) | ✅ | Separate `migrate` service; started in production mode by the restore drill and the load test |
| Least-privilege database role for the API; production refuses a privileged role | ✅ | `test_tenancy.py` (privilege matrix), restore drill (roles in production) |
| PostgreSQL row-level security on every tenant table (organisation, and hotel for hotel requests) | ✅ | Migration 0010; whole backend suite runs as the restricted role; `test_tenancy.py` (second organisation invisible in API and SQL, writes refused, tables without policy fail the test) |
| Access control over every API operation (session, CSRF, other organisation's hotel, no permission) | ✅ | `test_security.py`, generated from the OpenAPI schema (226 operations) |
| Security audit | ✅ | `docs/security/audit-2026-11.md`: 9 findings fixed (1 high: client IP spoofing through X-Forwarded-For) |
| Automated backups, each verified by restoring into a scratch database | ✅ | `backup-once.sh` |
| Backups screen: service state, backups, history, back up now, restore with re-authentication | ✅ | `test_backups.py`, E2E `backups.spec.ts`, restore drill |
| Restore from the screen (checksum, new database, safety backup with the API frozen, switch by renaming) and from the command line | ✅ | `deploy/tests/restore-drill.sh` passed 2026-11-13 on the production stack (restore in 13 s) |
| CI pipeline (lint, tests, i18n, build, Docker images, dependency audits) | ✅ | |
| End-to-end suite (Playwright) | ✅ | Desktop, iPad, Android tablet locally; plus iPad Safari (WebKit) in CI |
| Load test (front desk mix, booking contention, real-time fan-out) on the production stack | ✅ | `deploy/tests/load-test.sh`; results in `docs/qa/phase10-report.md` |
| Khmer dates on browsers without Khmer data (desktop Chrome) | ✅ | Found during this phase: dates were shown in the device's language; Khmer month/weekday names now built in (`lib/intl.ts`, unit-tested) |
| External penetration test | ⬜ | Recommended before hosting several organisations on one server or exposing it to the Internet |
| Documentation screenshots (28) from a generated demo hotel, reproducible | ✅ | `tools/screenshots/`; tour in `docs/guides/screens.md` |
