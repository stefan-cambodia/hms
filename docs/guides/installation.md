# Installation and Operations Guide

## 1. Choose where the server runs

| Option | When | Internet outage |
|--------|------|-----------------|
| **A. Dedicated small PC or mini-server inside the hotel** (recommended) | Any hotel; works with an unreliable Internet connection | Operations continue on the LAN |
| B. Existing LAN server / NAS that can run Docker | Hotels with IT equipment | Operations continue |
| C. Cloud VM (any provider) | Reliable connection plus a 4G backup | Operations stop until the link returns |

Minimum hardware: 2 CPU cores, 4 GB RAM, 40 GB SSD, wired Ethernet. Ubuntu 24.04 LTS or Debian 12 recommended.

## 2. Install the server (Linux)

```bash
# Docker Engine + Compose plugin
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER   # log out and back in

# Application
git clone <repository-url> hms && cd hms/deploy
cp .env.example .env
```

Edit `.env`:

* `POSTGRES_PASSWORD`: generate with `openssl rand -base64 32`.
* `HMS_DATA_KEY`: generate with the command in the file. **Store a copy of this key somewhere safe outside the server** (a password manager or a printed sealed envelope). Encrypted fields (2FA secrets, OTA credentials, identity documents) cannot be recovered without it, even from backups.
* `HMS_SITE_ADDRESS` and `HMS_TLS`:
  * LAN: `HMS_SITE_ADDRESS=https://hms.lan`, `HMS_TLS=internal`. Add `hms.lan` to your router's local DNS (or each device's hosts file), pointing to the server's fixed IP address.
  * Cloud: `HMS_SITE_ADDRESS=hotel.example.com`, `HMS_TLS=you@example.com`. Point the domain's DNS A record to the server first.

Start and create the first administrator:

```bash
docker compose up -d --build
docker compose exec api hms-entrypoint cli bootstrap \
  --org "Your Company" --hotel "Your Hotel" --code HOTEL \
  --admin-email admin@yourhotel.com --admin-name "Your Name" \
  --timezone Asia/Phnom_Penh --currency USD --language en
# You will be prompted for the administrator password (min. 10 characters).
```

Open `https://hms.lan` (or your domain), sign in, and follow the **Set up your hotel** checklist on the dashboard.

### Upgrades

```bash
cd hms && git pull && cd deploy
docker compose exec backup /scripts/backup-once.sh   # safety backup first
docker compose up -d --build                          # migrations run automatically on start
```

Every device picks up the new interface automatically, because the UI is served by the server.

## 3. Trust the local certificate (LAN option only)

With `HMS_TLS=internal`, Caddy creates a private certificate authority. Each device must trust it **once**:

```bash
docker compose cp web:/data/caddy/pki/authorities/local/root.crt ./hms-root-ca.crt
```

* **Windows:** double-click `hms-root-ca.crt` › Install Certificate › Local Machine › *Trusted Root Certification Authorities*.
* **Ubuntu / Debian / Mint:** `sudo cp hms-root-ca.crt /usr/local/share/ca-certificates/ && sudo update-ca-certificates`. Firefox: Settings › Certificates › Import.
* **Android:** Settings › Security › Encryption & credentials › Install a certificate › CA certificate.
* **iPad:** AirDrop or email the file, open it, then Settings › General › VPN & Device Management › install the profile, then Settings › General › About › Certificate Trust Settings › enable full trust.

## 4. Connect staff devices

* **Desktop application (Linux/Windows):** install *HMS* — `.deb` (Ubuntu, Debian, Mint), `.AppImage` (any recent Linux, no installation), Windows installer, or the portable `.exe` (Windows 10 21H2+ and 11). At first start, enter the server address and press *Connect*: the address is remembered, and the hotel's interface opens. *Server › Change server…* chooses another one. If the computer does not trust the server's certificate, the screen says so: install the certificate first (section 3). The application stores nothing else on the computer. See `desktop/README.md`.
* **Desktop in a browser:** the address also works in Chrome, Edge or Firefox.
* **Android tablet:** Chrome › menu › *Add to home screen*.
* **iPad:** Safari › Share › *Add to Home Screen*.

Each staff member signs in with their own account and chooses their own language (top bar, or *My account*).

## 5. Backups

The `backup` service runs every `BACKUP_INTERVAL_HOURS` (default 6). For each backup it:

1. dumps the database (`pg_dump`, compressed custom format),
2. **verifies it by restoring it into a temporary database** and checking the tables,
3. keeps it only if verification succeeded, with a SHA-256 checksum,
4. deletes backups older than `BACKUP_RETENTION_DAYS`, always keeping the three newest.

The result of the last run is in `deploy/backups/last-run.json` (`"status": "ok"` or `"failed"` with the reason).

**Off-machine copies:** set `BACKUP_HOST_DIR` to a mounted external drive or network share, or copy `deploy/backups/` off-site with a scheduled `rsync`/`rclone`. A backup kept only on the server is lost along with the server.

Manual backup at any time: `docker compose exec backup /scripts/backup-once.sh`.

## 6. Restore and disaster recovery

```bash
cd hms/deploy
./scripts/restore.sh backups/hms-YYYYMMDDTHHMMSSZ.dump
```

The script verifies the checksum, asks for confirmation, takes a safety backup of the current data, stops the API, restores, and restarts. Staff devices reconnect automatically.

**Full server loss:** install a new server (section 2) with the **same `HMS_DATA_KEY`**, copy a backup file into `deploy/backups/`, start the stack, then run `restore.sh`. Test this procedure at least once a year on a spare machine. A backup that has never been restored should not be trusted.

## 7. Channel manager (SiteMinder)

Optional. Without it the PMS works fully, and OTA bookings are entered by hand
with their source.

1. **Prerequisites:** a SiteMinder subscription for the hotel. The software
   vendor must also be a SiteMinder pmsXchange partner (certification with a
   pilot hotel). SiteMinder then gives a PMS code, a username and password, and
   the hotel code. Booking.com, Agoda and the other channels are connected
   inside SiteMinder.
2. The server needs **outgoing HTTPS** (port 443) to SiteMinder. No incoming
   connection is needed: reservations are pulled every 2 to 5 minutes.
3. In *Channel manager*, add the connection (test environment first), then:
   * run **Test connection**;
   * on the *Mapping* tab, **Get codes from SiteMinder** and give each room
     type and rate plan its code;
   * switch on sending, then receiving reservations.
4. The synchronisation runs inside the API service. With several API
   processes, one of them takes the lead automatically. Set
   `HMS_CHANNEL_WORKER_ENABLED=false` only to stop it, for example on a
   restored copy of the database that must not talk to SiteMinder.
5. The *Activity log* tab shows every exchange (passwords and card numbers
   removed). Errors are retried automatically with increasing delays.

## 8. Troubleshooting

| Symptom | Check |
|---------|-------|
| Devices show "Disconnected" | Is the server on (`docker compose ps`)? Can the device reach its IP? Is it on the hotel Wi-Fi rather than a guest network isolated from the server? |
| Browser certificate warning | Section 3: the device does not trust the local CA yet. |
| Cannot sign in, "Account temporarily locked" | Wait for the indicated delay, or an administrator unlocks the account in *Users & permissions*. |
| `last-run.json` shows `failed` | `docker compose logs backup`: usually a full disk or an unreachable backup directory. |
| Channel manager shows "Errors" | *Channel manager › Activity log*: authentication errors mean wrong credentials; unknown codes mean the mapping must be fixed; network errors are retried automatically. |
| Logs | `docker compose logs -f api` · `docker compose logs -f web` |
