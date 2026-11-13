# 4. Security Strategy

## 4.1 Authentication

* **Passwords** are hashed with Argon2id (`argon2-cffi` defaults, which meet
  OWASP 2024 parameters) and rehashed transparently when the parameters change.
  The minimum is 10 characters, and passwords are checked against a bundled
  common-password list. Plaintext passwords are never stored or logged.
* **Sessions** use opaque tokens rather than JWTs: a 256-bit random token is
  issued at login and only its SHA-256 hash is stored in `user_sessions`.
  * Revocation takes effect immediately (the next request fails), which JWT
    access tokens can't offer without a denylist.
  * The data needed for "connected users", "last activity", and "revoke
    session" comes for free.
  * There is an idle timeout (default 12 h, configurable) and an absolute
    lifetime (default 7 days). `last_seen_at` is updated at most once per minute.
* **Transport.** Browsers, tablets, and the desktop shell all load the SPA from
  the server, so the token travels in an `httpOnly; Secure; SameSite=Strict`
  cookie that JavaScript can't read. Scripts and integrations may instead send
  `Authorization: Bearer <token>`.
* **CSRF.** Cookie-authenticated, state-changing requests must carry an
  `X-CSRF-Token` header equal to the session's own random token (stored with
  the session, returned at login), on top of `SameSite=Strict`. Bearer
  requests are exempt because browsers never attach them automatically. A
  test sends every state-changing API operation without the header and
  expects a refusal (`test_security.py`).
* **Brute force.** Login is rate-limited per IP and per account; after 5
  failures an account is temporarily locked with exponential backoff. The
  per-IP counters are stored in PostgreSQL (an unlogged table), so the limit
  holds across several API processes or servers. Every attempt goes to
  `login_events`.
* **2FA.** Optional TOTP (RFC 6238) per user; the secret is encrypted at
  rest. A user who lost their phone is helped by an administrator
  (`users.manage`): *Reset two-factor authentication* switches it off and ends
  all of that user's sessions, and is audited. Not built yet: recovery codes,
  and making 2FA mandatory per role.

## 4.2 Authorisation (RBAC)

* Permissions are fine-grained codes (`reservations.create`,
  `payments.refund`, `config.rooms.manage`, …) defined in one catalog
  (`backend/app/core/permissions.py`). The frontend receives the user's
  effective permissions only to hide actions; **every endpoint enforces its
  permission on the server**.
* Roles are bundles of permissions. The system roles (Super Administrator,
  Hotel Administrator, Manager, Receptionist, Reservation Manager,
  Housekeeping, Accountant, Maintenance) are seeded and protected;
  administrators can clone them or create custom roles.
* Roles are granted **per hotel** (`user_hotel_roles`), which is how tenant
  isolation works for users. `is_superadmin` is reserved for
  organisation-level administration.
* **Tenant isolation in the database (row-level security, migration 0010).**
  The application filters every query by hotel, and PostgreSQL enforces the
  same boundary independently: every table holding tenant data has a policy,
  and each transaction declares its tenant (`app/core/tenancy.py`: the
  organisation once the session is resolved, narrowed to the hotel after the
  hotel permission check). A query that forgets its `hotel_id` filter returns
  the current hotel's rows, never another organisation's; writing a row for
  another tenant is refused. Without a declared tenant nothing is visible.
  The few lookups needed before the organisation is known (login by e-mail,
  session token, "is the system initialised", the channel worker's list of
  connections) are narrow `SECURITY DEFINER` functions returning identifiers
  only. Tests check that every table is covered (`test_tenancy.py`) and that
  every API operation hides other organisations' hotels (`test_security.py`).
  Threat covered: application bugs (a missing filter, a wrong identifier). It
  is not a defence against someone able to run arbitrary SQL as the API's
  role, who could also set the tenant variables.
* Sensitive guest data (identity document numbers, date of birth) requires
  `guests.view_sensitive`, and reads of it are audited.

## 4.3 Data protection

* **Payment cards:** no primary account number (PAN), CVV, or track data is
  ever stored. Only brand, last 4 digits (database check `^[0-9]{4}$`), and a
  processor reference, which keeps the PMS out of PCI DSS scope for stored
  card data. Free-text fields where staff could paste a card number (payment
  reference and notes, charge descriptions, reservation and guest notes, void
  reasons) reject any 13–19 digit sequence that passes the Luhn check
  (`card_number_not_allowed`).
* **Financial records:** folio charges, payments and invoices, restaurant
  payments and vehicle rental payments are append-only. A database trigger refuses deletes and any update other than
  voiding (with a mandatory reason); a void cannot be undone. Invoice and
  receipt numbers are gapless. Waiving fees, discounts, voiding charges and
  checking out with money owed need `folio.adjust`; refunds and payment voids
  need their own permissions. Every financial action is in the reservation
  history and the audit log. Once a business day is closed (end of day), its
  charges and the payments received that day can no longer be posted, voided
  or changed; the closure record itself is append-only.
* **Documents:** PDFs are rendered server-side from escaped templates; the
  renderer is not allowed to fetch any URL (no SSRF through documents).
* **Channel manager:** provider credentials are encrypted at rest, write-only
  in the API and never written to the audit log. Every message body is
  redacted before it is stored (passwords, card numbers and CVC removed, any
  Luhn-valid 13–19 digit sequence masked). Reservations received from a channel
  keep only the card brand and last 4 digits. XML from the provider is parsed
  with `defusedxml` (no entity expansion, no external references). Outgoing
  calls only go to the configured provider endpoint over HTTPS, with no
  redirects followed.
* **Encryption at rest** for secrets that must be recoverable (OTA
  credentials, TOTP secrets, identity document numbers, renters' driving
  licence numbers, of which screens and contracts show only the last 4 digits): AES-GCM through
  `cryptography`'s Fernet-compatible scheme, with the key provided by the
  `HMS_DATA_KEY` environment variable or a secrets file, and never in the
  database or its backups. Backups are therefore useless without the key, and
  the key must be backed up separately, as the disaster recovery runbook states.
* **Uploads (photos and logos, `media` module):** one image per request,
  at most 15 MB (bodies over 16 MB are refused by the API before they are
  read, and by Caddy above 20 MB). The type comes from the file's first bytes
  (JPEG, PNG or WebP; the name and declared type are ignored; SVG, PDF, GIF
  and HEIC are refused). Images over 64 megapixels are refused before
  decoding (decompression bombs), truncated or damaged files are refused
  (never completed with grey, even though the PDF library switches Pillow's
  process-wide tolerance on), and decoding runs in a worker thread, two at a
  time per API process. Every image is decoded and encoded again
  (JPEG, or PNG for a logo with transparency), turned upright, converted to
  sRGB and scaled down (photos 2048 px, logos 1024 px): the stored file has
  no EXIF, GPS position, comments or embedded profile. Files are kept in
  PostgreSQL under row-level security and served only to staff who may see
  their owner (maintenance photos need `maintenance.view`), as `image/jpeg`
  or `image/png` with `nosniff`, `Content-Disposition: inline` and a private
  cache. PDF rendering may load only `data:` URLs (the logo), never a file
  or the network.
* **Retention (not built yet):** planned configurable purge or anonymisation
  of guest PII after N years, per-guest export and erasure, financial records
  kept as tax law requires with the guest identity anonymised.

## 4.4 Application security

* **SQL injection:** only parameterised queries through SQLAlchemy; no string
  concatenation into SQL.
* **XSS:** React escapes all output and the code never uses
  `dangerouslySetInnerHTML` (checked in the 2026-11 audit; there is no lint
  rule yet); a strict CSP is set by Caddy (`default-src 'self'`, no inline
  script; inline styles are allowed for the UI library). PDF templates use
  Jinja2 with autoescape.
* **Input validation:** Pydantic models with explicit types, length limits,
  and enums on every endpoint; unknown fields are rejected.
* **Security headers** (set by Caddy): HSTS, CSP, `X-Frame-Options: DENY`,
  `Referrer-Policy: same-origin`, `Permissions-Policy`.
* **Audit:** every write through a service records an `audit_logs` row
  (who, what, before/after diff, IP, request ID), in the same transaction as
  the change. The audit table is append-only: a trigger rejects UPDATE/DELETE
  (even for the schema owner) and the API's role has no UPDATE/DELETE
  privilege on it.
* **Client address:** Caddy is the only entry point and replaces any
  `X-Forwarded-For` sent by a client (`HMS_TRUSTED_PROXIES` only when another
  proxy sits in front), so the address used for throttling and recorded in the
  login history and audit trail cannot be chosen by a device on the network.
* **Rate limiting:** sign-in attempts per IP address (shared by all API
  processes) plus per-account lockout; password re-checks of a signed-in user
  (change password, disable 2FA, confirm a restore) are limited to 5 per
  5 minutes per account. There is no general per-IP request limit (Caddy's
  standard build has none).
* **Dependencies:** `pip-audit` and `npm audit` (shipped dependencies, high
  severity and above) run in CI. No automatic update bot is configured.
* **Least privilege (migration 0010):** the API logs in as `hms_api`, a member
  of `hms_app`: rows only, no DDL, no TRUNCATE, no UPDATE/DELETE of
  append-only records, subject to row-level security. Migrations, role
  provisioning and installation-wide commands run in the separate `migrate`
  service as the schema owner; the API container never receives the owner's
  password. In production the API refuses to start if its role is a
  superuser, bypasses row-level security, or owns the tables. The API
  container runs as a non-root user.

## 4.5 Backups and restore

* A separate `backup` container (PostgreSQL tools, no Docker access) makes a
  verified backup every `BACKUP_INTERVAL_HOURS`: each dump is restored into a
  scratch database and checked before it is kept, with a SHA-256 checksum.
  Backup files are readable by root only (guest personal data).
* The Backups screen (`backups.manage`) shows the service state, the backups
  and the history, and can request a backup. A **restore** from the screen is
  limited to super administrators of a single-organisation installation, asks
  for the password (and 2FA code) again and for the hotel's code, and only
  accepts backups made by the same software version. The API only drops a
  request file into a shared folder; the backup service checks the request
  again, verifies the checksum, loads the backup into a new database, takes a
  safety backup of the current data while the API's role is refused
  connections, then switches databases by renaming. The restore is recorded
  in every hotel's audit trail of the restored data.

## 4.6 Network

* HTTPS is used everywhere, including on the LAN: Caddy `tls internal`
  generates a local CA, and the installation guide covers trusting it on
  Windows, Linux, Android, and iPadOS. Alternatively, a real domain with a
  DNS-01 certificate works on the LAN without trusting a custom CA.
* PostgreSQL is never exposed outside the Docker network.
* Caddy's `trusted_proxies` defaults to nothing outside the container (see
  "Client address" above).
* OTA traffic is outbound only (pull model where the OTA supports it), so the
  hotel network needs no inbound port forwarding. If an OTA requires push
  delivery, the documented option is a cloud relay or a cloud deployment.

## 4.7 Security audit

The phase 10 audit (method, findings, fixes, residual risks) is in
`docs/security/audit-2026-11.md`.
