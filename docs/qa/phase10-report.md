# Phase 10 — final QA report (2026-11-13)

What was verified before the first installation in a hotel, how, and with
which results. The security audit is in `docs/security/audit-2026-11.md`.

## 1. Automated tests

| Suite | Result | Notes |
|-------|--------|-------|
| Backend (pytest, real PostgreSQL) | 163 passed, 1 skipped (opt-in live SiteMinder test) | Run as the least-privilege role `hms_api`: row-level security and the append-only grants apply to every test. New: `test_tenancy.py` (7), `test_security.py` (5, every API operation), `test_backups.py` (5), 2FA reset |
| Frontend unit (Vitest) | 38 passed | New: file sizes, Khmer dates without browser data, plural guest counts |
| End-to-end (Playwright, desktop, iPad landscape, Android tablet) | 54 passed, 0 failed, 36 skipped by design (flows checked on one device) | New: Backups screen; iPad Safari (WebKit) runs in CI |
| Translation completeness | 2152 keys × 5 languages | |
| Migration 0010 | upgrade → downgrade → upgrade on a scratch database | No policy or function left after the downgrade; 62 policies after the upgrade |

## 2. Restore drill on the production stack

`deploy/tests/restore-drill.sh` builds a throwaway copy of the production
stack (Caddy, `migrate`, API with 2 processes, PostgreSQL, backup service),
then works through the API exactly as the Backups screen does. Run on
2026-11-13, final run:

```
== Build and start the production stack
   PASS  migrate service completed, API healthy in production mode
== Database roles
   PASS  API connected as hms_api (not superuser, no BYPASSRLS)
== First administrator (CLI, application role)
   PASS  bootstrap
== Forwarded header from a client
   PASS  login recorded from 172.22.0.1, not the spoofed 203.0.113.77
== Backup from the API
   PASS  backup hms-20261113T021951Z.dump (291065 bytes, test restore of 62 tables)
== Restore from the API
   PASS  restore finished in about 13 s; safety backup hms-20261113T022001Z.dump
   PASS  data is back to the backup (AFTER is gone)
   PASS  restore recorded in the audit trail
   PASS  safety backup listed
   PASS  the running API writes to the restored database (HTTP 201), no restart
== Drill passed
```

The earlier runs of the drill found three defects, fixed before the final run:

1. the metadata file of each backup was written as `…dump.json` instead of
   `….json`, so the screen did not know a backup was restorable;
2. a restore's safety backup carries the restore's request identifier; the
   screen would have announced "backup completed" in the middle of a restore
   (it now matches the kind of operation too);
3. the restore entry was written to the audit trail without a hotel, so no
   hotel's audit screen showed it (now one entry per hotel).

## 3. Load test

`deploy/tests/load-test.sh` starts a throwaway copy of the production stack
(Caddy, API with `HMS_WORKERS=2`, PostgreSQL, backup service), prepares the
hotel through the API (120 rooms of one category, 1,500 reservations over the
past 60 and next 120 days, 25 receptionists and 5 managers) and measures from
the same machine. Raw results: `docs/qa/load-test-2026-11-13.json` and the
containers' CPU/memory samples `docs/qa/load-test-2026-11-13-containers.csv`.

**Machine and conditions.** Intel Core Ultra 7 155H (22 threads), 15 GiB RAM,
Linux; client and server on the same machine. This is a shared workstation:
during the run, unrelated heavy jobs were running (audio analysis, game
rendering; host load average about 12), so the figures are pessimistic. An
earlier run was discarded because the laptop went to sleep during the
measurement; the script now detects any pause of the machine
(`host_paused_seconds`: 0.0 for this run) and keeps it awake while measuring.

### 3.1 Front desk mix: 30 staff for 5 minutes

Each person repeats a screen action every 0.5–2 s (about 0.8 actions per
second each: several times the pace of real front-desk work), across
dashboard, front desk, room board, calendar, availability, searches,
reservation detail, housekeeping, the 30-day performance report (managers)
and creating/cancelling reservations. All 30 book into the same category.

6,621 requests, 21.9 per second, **0 errors**.

| Operation | Count | p50 | p95 | p99 | max |
|-----------|------:|----:|----:|----:|----:|
| reservation detail | 921 | 62 ms | 419 ms | 783 ms | 1.7 s |
| availability search (3 nights, all categories) | 705 | 66 ms | 538 ms | 935 ms | 2.4 s |
| housekeeping tasks | 299 | 64 ms | 640 ms | 951 ms | 2.4 s |
| guest search | 339 | 90 ms | 624 ms | 1.4 s | 2.4 s |
| room board | 555 | 114 ms | 652 ms | 1.1 s | 1.4 s |
| reservation search | 434 | 130 ms | 796 ms | 1.2 s | 1.7 s |
| front desk (arrivals, departures, in house) | 602 | 136 ms | 794 ms | 1.4 s | 2.4 s |
| performance report, 30 days (managers) | 36 | 200 ms | 968 ms | 1.5 s | 1.7 s |
| calendar, 14 days × 120 rooms | 686 | 309 ms | 1.1 s | 1.7 s | 2.8 s |
| dashboard (today's figures) | 557 | 333 ms | 1.2 s | 1.8 s | 2.9 s |
| cancel reservation | 566 | 189 ms | 1.2 s | 1.8 s | 3.9 s |
| create reservation | 921 | 281 ms | 1.6 s | 2.4 s | 3.7 s |

Reading:

* Slow requests (over 1 s: 313 of 6,621, 134 of them creations) are not
  spread evenly: 40 in the first 30 s, when all 30 sessions start at the same
  instant, 171 between minutes 2 and 3, few elsewhere. The other jobs on the
  machine were not recorded, so whether that window matches them is not known.
* **Bookings in one category are serialised on purpose**: a creation holds
  its category's lock from the availability check to the commit, which is
  what makes overselling impossible (section 3.2). The test puts 30 people on
  the same category, the worst case, so creations wait for one another.
  Cancellations do not take that lock; their tail follows the general load.
* While busy, the API processes used about 1.2 CPU cores on average, peaking
  at 2.4 (2 processes); PostgreSQL about 0.9, peaking at 1.6. Memory: API up
  to 280 MiB, PostgreSQL up to 455 MiB, Caddy under 100 MiB. With
  `HMS_WORKERS=2` the API processes are the limit at this pace: for a large
  hotel, set `HMS_WORKERS` to the server's number of cores.

### 3.2 Booking contention

50 simultaneous bookings from 30 sessions, through Caddy to the 2 API
processes, for one night in a new category of 3 rooms: **exactly 3 accepted (201), 47 refused
(409), availability 0 afterwards**, in 3.6 s. No room allocated twice (the
database's exclusion constraint would have refused it in any case).

### 3.3 Real-time updates

60 devices connected over WebSocket through Caddy; one change made: **all 60 received the event, median 47 ms, slowest 57 ms**
after the change was sent (the request itself included).


## 4. Other defects found and fixed in this phase

* **Khmer dates in the device's language.** Desktop Chrome has no Khmer
  formatting data; every date of the Khmer interface was shown in the
  device's own language (French on the test machine). Dates now use Khmer
  month and weekday names when the browser lacks the data (`lib/intl.ts`);
  Safari on iPad formats natively. Seen on the new Backups screen, but it
  affected every screen.
* **Throttled sign-ins never recovered when retried at the limit's pace**
  (found by the load test's own sign-ins): refused attempts count, by design.
  Documented, and `HMS_LOGIN_RATE_PER_MINUTE` is now configurable in the
  production stack for cloud servers reached by a whole hotel through one
  public address.
* **Found while taking the documentation screenshots** (`tools/screenshots/`,
  a demo hotel with five weeks of history):
  * occupancy above 100 % (1,083 % for the month) when stays are entered for
    nights before the rooms' creation date: a room sold on a night now counts
    as available that night (`test_reports.py`);
  * negative average booking lead time for bookings entered after arrival
    (walk-ins typed in later, history): such a booking now counts 0;
  * "1 adults · 0 children" in English (and the matching forms in French,
    Russian): the guests count now uses each language's plural forms and leaves
    out zero children (unit test).
* Images of the drill and of a real installation shared the tag `hms-api`:
  running the drill on a production server could have replaced the image of
  the running stack. Images are now named per Compose project.

## 5. Not verified

* Physical iPad and Android tablets, real Linux and Windows computers with
  the desktop installers (phase 9).
* Behaviour with a database much larger than the load test's (years of a
  large hotel's history).
* An external penetration test.
