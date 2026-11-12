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
  `X-CSRF-Token` header matching the `hms_csrf` cookie (double-submit), on top
  of `SameSite=Strict`. Bearer requests are exempt because browsers never
  attach them automatically.
* **Brute force.** Login is rate-limited per IP and per account; after 5
  failures an account is temporarily locked with exponential backoff. The
  per-IP counters are stored in PostgreSQL (an unlogged table), so the limit
  holds across several API processes or servers. Every attempt goes to
  `login_events`.
* **2FA.** Optional TOTP (RFC 6238) per user, which administrators can make
  mandatory per role. The secret is encrypted at rest; recovery codes are
  stored hashed.

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
  history and the audit log.
* **Documents:** PDFs are rendered server-side from escaped templates; the
  renderer is not allowed to fetch any URL (no SSRF through documents).
* **Encryption at rest** for secrets that must be recoverable (OTA
  credentials, TOTP secrets, identity document numbers, renters' driving
  licence numbers, of which screens and contracts show only the last 4 digits): AES-GCM through
  `cryptography`'s Fernet-compatible scheme, with the key provided by the
  `HMS_DATA_KEY` environment variable or a secrets file, and never in the
  database or its backups. Backups are therefore useless without the key, and
  the key must be backed up separately, as the disaster recovery runbook states.
* **Uploads:** size limits; type checked from magic bytes and whitelisted
  (JPEG, PNG, WebP, PDF); images re-encoded server-side (which strips EXIF
  location data); stored outside the web root under random names; served with
  `Content-Disposition` and `X-Content-Type-Options: nosniff`.
* **Retention:** configurable purge or anonymisation of guest PII after N
  years, plus per-guest export (JSON + PDF) and erasure. Financial records are
  kept as tax law requires, with the guest identity anonymised.

## 4.4 Application security

* **SQL injection:** only parameterised queries through SQLAlchemy; no string
  concatenation into SQL.
* **XSS:** React escapes all output; `dangerouslySetInnerHTML` is banned by
  lint; a strict CSP is set by Caddy (`default-src 'self'`, no inline script).
  PDF/email templates use Jinja2 with autoescape.
* **Input validation:** Pydantic models with explicit types, length limits,
  and enums on every endpoint; unknown fields are rejected.
* **Security headers** (set by Caddy): HSTS, CSP, `X-Frame-Options: DENY`,
  `Referrer-Policy: same-origin`, `Permissions-Policy`.
* **Audit:** every write through a service records an `audit_logs` row
  (who, what, before/after diff, IP, request ID), in the same transaction as
  the change. The audit table is append-only (a trigger rejects
  UPDATE/DELETE).
* **Rate limiting:** login and password-reset are limited in the application,
  and Caddy applies a general per-IP limit.
* **Dependencies:** `pip-audit` and `npm audit` run in CI; Dependabot or
  Renovate keep them up to date.
* **Least privilege:** the API connects as `hms_app`, which can't run DDL;
  migrations run as `hms_owner`. The containers run as non-root with
  read-only root filesystems where possible.

## 4.5 Network

* HTTPS is used everywhere, including on the LAN: Caddy `tls internal`
  generates a local CA, and the installation guide covers trusting it on
  Windows, Linux, Android, and iPadOS. Alternatively, a real domain with a
  DNS-01 certificate works on the LAN without trusting a custom CA.
* PostgreSQL is never exposed outside the Docker network.
* OTA traffic is outbound only (pull model where the OTA supports it), so the
  hotel network needs no inbound port forwarding. If an OTA requires push
  delivery, the documented option is a cloud relay or a cloud deployment.
