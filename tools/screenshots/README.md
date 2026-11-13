# Documentation screenshots

The pictures in `docs/images/` (used by the README and `docs/guides/`) are
taken from a dedicated demo database, never from a hotel's data:

1. **Database** (development PostgreSQL container `hms-dev-db`): a fresh
   `hms_shots` database with the demo hotel (`hms bootstrap` + `hms seed-demo`):

   ```bash
   tools/screenshots/reset-db.sh
   ```

2. **API on that database** (port 8000; the channel worker is off, so nothing
   is ever sent to SiteMinder):

   ```bash
   cd backend
   HMS_DATABASE_URL=postgresql+asyncpg://hms_api:hms_api_dev_password@127.0.0.1:54329/hms_shots \
   HMS_CHANNEL_WORKER_ENABLED=false HMS_COOKIE_SECURE=false \
   HMS_BACKUP_CONTROL_DIR=/tmp/hms-shots/control .venv/bin/uvicorn app.main:app --port 8000
   ```

3. **Activity**: guests in house, today's arrivals and departures, five
   weeks of history, folios and payments, housekeeping, maintenance,
   restaurant checks, vehicle rentals, a SiteMinder test connection
   (sending and receiving off):

   ```bash
   backend/.venv/bin/python tools/screenshots/seed_activity.py --base http://127.0.0.1:8000 \
     --email admin@demo.local --password Demo-Admin-2026 \
     --owner-dsn postgresql://hms:hms_dev_password@127.0.0.1:54329/hms_shots
   ```

   What the API rightly refuses to do in the past (check-ins on earlier days,
   stays that already ended, payments received then) is back-dated through the
   schema owner's connection.

4. **Backups screen** (optional): run the backup service image against
   `hms_shots`, sharing `/tmp/hms-shots/control` as its `/control` folder
   (`HMS_API_UID` = your user id), and let it make a backup or two.

5. **Screenshots**: with `npm run dev` running in `frontend/`:

   ```bash
   node tools/screenshots/shoot.mjs
   ```

   Desktop 1440×900, iPad Pro 11" landscape, Android tablet portrait; English
   plus one screen each in Khmer, Chinese, French and Russian; the desktop
   application's connection screen (its page served locally, the calls to
   the application stubbed).

6. **User guide** (`docs/guides/user-guide.fr.md`, `.en.md`, `.km.md`): the
   same twelve screens in French, English and Khmer, into `docs/images/guide/`:

   ```bash
   node tools/screenshots/guide.mjs
   ```
