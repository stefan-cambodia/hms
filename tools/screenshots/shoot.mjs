// Screenshots for the documentation (docs/images/).
//
//   1. tools/screenshots/reset-db.sh, then seed_activity.py (see README.md)
//   2. API on :8000 against that database, `npm run dev` in frontend/ (:5173)
//   3. node tools/screenshots/shoot.mjs
//
// English interface unless stated; desktop 1440×900, iPad Pro 11" landscape,
// Android tablet portrait. Each page is shot once the real-time connection
// is live and the data has loaded.
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(new URL('../../frontend/package.json', import.meta.url));
const { chromium } = require('@playwright/test');

const BASE = process.env.SHOTS_BASE ?? 'http://localhost:5173';
const EMAIL = process.env.SHOTS_EMAIL ?? 'admin@demo.local';
const PASSWORD = process.env.SHOTS_PASSWORD ?? 'Demo-Admin-2026';
const OUT = fileURLToPath(new URL('../../docs/images/', import.meta.url));
const LIVE = { en: 'Live', fr: 'Connecté', km: 'បានភ្ជាប់', 'zh-CN': '在线', ru: 'В сети' };

const DESKTOP = { viewport: { width: 1440, height: 900 } };
const IPAD = { viewport: { width: 1194, height: 834 }, hasTouch: true, isMobile: true };
const ANDROID = { viewport: { width: 800, height: 1280 }, hasTouch: true, isMobile: true };

const browser = await chromium.launch({ channel: 'chrome' });

async function session(device, lang = 'en') {
  const ctx = await browser.newContext({ ...device, baseURL: BASE, deviceScaleFactor: 1, locale: 'en-GB', timezoneId: 'Asia/Phnom_Penh' });
  const page = await ctx.newPage();
  const r = await page.request.post('/api/v1/auth/login', { data: { email: EMAIL, password: PASSWORD } });
  const me = await r.json();
  const api = async (method, path, data) => {
    const res = await page.request.fetch(`/api/v1${path}`, { method, data, headers: { 'X-CSRF-Token': me.csrf_token } });
    return res.json();
  };
  await api('PATCH', '/auth/me', { preferred_language: lang });
  await page.goto('/');
  await page.evaluate((l) => localStorage.setItem('hms.language', l), lang);
  const h = (p) => `/hotels/${me.hotels[0].id}${p}`;
  return { ctx, page, api, h, lang };
}

async function shot(s, path, name, { full = false, prepare } = {}) {
  await s.page.goto(path);
  await s.page.getByText(LIVE[s.lang], { exact: true }).first().waitFor({ timeout: 20_000 });
  await s.page.waitForLoadState('networkidle');
  if (prepare) await prepare(s.page);
  await s.page.waitForTimeout(700);
  await s.page.screenshot({ path: `${OUT}${name}.png`, fullPage: full });
  console.log('shot', name);
}

// --- Desktop, English ------------------------------------------------------------
const d = await session(DESKTOP);
const find = async (q) => (await d.api('GET', d.h(`/reservations?q=${encodeURIComponent(q)}&limit=5`))).items[0];
const camille = await find('Durand');

await shot(d, '/', 'dashboard');
await shot(d, '/front-desk', 'front-desk');
await shot(d, '/calendar', 'calendar');
await shot(d, `/reservations/${camille.id}`, 'reservation', { full: true });
await shot(d, '/reservations', 'reservations', {
  prepare: async (page) => {
    await page.getByText('In house', { exact: true }).click();
    await page.waitForLoadState('networkidle');
  },
});
await shot(d, '/guests', 'guests');
await shot(d, '/housekeeping', 'housekeeping');
await shot(d, '/maintenance', 'maintenance');
await shot(d, '/restaurant/floor', 'restaurant-floor');
await shot(d, '/restaurant/kitchen', 'restaurant-kitchen');
await shot(d, '/vehicles/schedule', 'vehicles-schedule');
await shot(d, '/pricing/calendar', 'pricing-calendar');
await shot(d, '/channels?tab=mapping', 'channels-mapping', { full: true });
await shot(d, '/reports', 'reports-performance', { full: true });
await shot(d, '/reports/forecast', 'reports-forecast', { full: true });
await shot(d, '/billing/payments', 'billing-payments');
await shot(d, '/users/list', 'users');
await shot(d, '/backups', 'backups', { full: true });
await shot(d, '/backups', 'backups-restore', {
  prepare: async (page) => {
    await page.getByTestId('backups-table').getByRole('button', { name: 'Restore…' }).first().click();
    await page.getByRole('dialog').waitFor();
  },
});
await d.ctx.close();

// --- Login page --------------------------------------------------------------------
{
  const ctx = await browser.newContext({ ...DESKTOP, baseURL: BASE, deviceScaleFactor: 1, locale: 'en-GB' });
  const page = await ctx.newPage();
  await page.goto('/');
  await page.evaluate(() => localStorage.setItem('hms.language', 'en'));
  await page.reload();
  await page.getByRole('button').first().waitFor();
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${OUT}login.png` });
  console.log('shot login');
  await ctx.close();
}

// --- Tablets -----------------------------------------------------------------------
const ipad = await session(IPAD);
await shot(ipad, '/calendar', 'ipad-calendar');
await shot(ipad, '/front-desk', 'ipad-front-desk');
await ipad.ctx.close();
const android = await session(ANDROID);
await shot(android, '/housekeeping', 'android-housekeeping');
await android.ctx.close();

// --- Other languages ---------------------------------------------------------------
for (const [lang, path, name] of [
  ['km', '/', 'km-dashboard'],
  ['zh-CN', '/front-desk', 'zh-front-desk'],
  ['fr', '/calendar', 'fr-calendar'],
  ['ru', '/reports', 'ru-reports'],
]) {
  const s = await session(DESKTOP, lang);
  await shot(s, path, name);
  await s.api('PATCH', '/auth/me', { preferred_language: 'en' });
  await s.ctx.close();
}

// --- Desktop application: connection screen (bundled page, Tauri calls stubbed) ------
{
  const ctx = await browser.newContext({ viewport: { width: 980, height: 700 }, deviceScaleFactor: 1, locale: 'en-GB' });
  const page = await ctx.newPage();
  await page.addInitScript(() => {
    window.__TAURI_INTERNALS__ = {
      invoke: async (cmd) => (cmd === 'check_server' ? { kind: 'ok', url: 'https://hms.lan' } : null),
    };
  });
  // Served under an http origin: module scripts do not run from file://.
  const ui = new URL('../../desktop/ui/', import.meta.url);
  const types = { html: 'text/html', js: 'text/javascript', css: 'text/css', svg: 'image/svg+xml' };
  await page.route('http://desktop.local/**', (route) => {
    const name = new URL(route.request().url()).pathname.slice(1) || 'index.html';
    route.fulfill({ path: fileURLToPath(new URL(name, ui)), contentType: types[name.split('.').pop()] ?? 'application/octet-stream' });
  });
  await page.goto('http://desktop.local/index.html');
  await page.locator('#language option').first().waitFor({ state: 'attached' });
  await page.fill('#url', 'hms.lan');
  await page.click('#test');
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${OUT}desktop-connect.png` });
  console.log('shot desktop-connect');
  await ctx.close();
}

await browser.close();
