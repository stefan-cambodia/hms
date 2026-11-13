# HMS desktop application

A thin [Tauri 2](https://tauri.app) shell around the web interface served by the
hotel's HMS server (architecture §1.4). It contains no business logic and no
database: every computer works on the hotel server.

| Platform | Package |
|----------|---------|
| Ubuntu 22.04+, Debian 12+, Linux Mint 21+ | `.AppImage` (no installation) and `.deb` |
| Windows 10 (21H2+) and 11 | NSIS installer (`*-setup.exe`, per user or for all users) and portable `.exe` |

## What the shell does

* **Connection screen** (bundled, 5 languages): enter the server address, test
  it, connect. The address is remembered (`settings.json` in the user's
  configuration folder). Plain `http://` is refused except for this computer.
  A certificate the computer does not trust is explained (install the hotel's
  certificate, installation guide §3). An HMS server is recognised by its
  `/api/v1/health` answer.
* **Then the window shows the hotel's interface, loaded from the server.** The
  interface version always matches the server; updating the server updates
  every computer.
* If the remembered server is unreachable at start-up, the connection screen
  retries every 10 seconds.
* **Navigation**: the window only shows the hotel server and the shell's own
  pages. Links to other sites open in the system browser; `file:`,
  `javascript:` and other schemes are refused.
* **Documents** (invoices, receipts, contracts) open in their own window, sharing
  the session. Downloaded PDFs go to the Downloads folder (never overwriting a
  file) and open in the system viewer, which prints.
* One instance: launching it again brings the window to the front.
* Menu *Server › Change server… / Reload / Quit*, in the system language.

**Security.** Pages from the hotel server get no access to the shell's
commands: the only capability (`src-tauri/capabilities/main.json`) covers the
bundled connection screen, and no remote URL is listed. Server checks use the
system's TLS (SChannel on Windows, OpenSSL on Linux), the same certificate store
as the window.

## Layout

```
core/          platform-independent decisions (addresses, navigation, errors,
               downloads, settings, menu labels) — unit tested
src-tauri/     the Tauri application (window, commands, menu, bundling)
ui/            the connection screen (plain HTML/JS, no network access of its own)
tests/         connection screen tests (node --test)
```

## Build

Installers are built by GitHub Actions (`.github/workflows/desktop.yml`):
Linux on Ubuntu 22.04 (so the AppImage runs on 22.04 and newer), Windows on
`windows-latest`. Download them from the workflow run's artifacts.

Locally:

```bash
cd desktop
cargo test -p hms-desktop-core    # logic tests, any OS
node --test tests/*.test.mjs      # connection screen
npm ci && npx tauri build         # needs WebKitGTK 4.1 on Linux, WebView2 on Windows
```

Icons are generated from `frontend/public/icon.svg` (`npm run icons`).

## Not done yet

* Code signing (Windows SmartScreen warns about unsigned installers until a
  certificate is bought; Linux packages are not signed).
* Automatic updates of the shell itself (the interface updates with the server).
* macOS build (not requested).
