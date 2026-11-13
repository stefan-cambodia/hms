// Screenshots for the staff user guide (docs/guides/user-guide.*.md): the same
// 12 screens in French, English and Khmer, desktop 1440×900.
//
//   Same set-up as shoot.mjs (README.md, steps 1 to 3), then:
//   node tools/screenshots/guide.mjs
//
// The demo hotel gets the logo of the end-to-end tests if it has none.
import { readFileSync, mkdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const REPO = fileURLToPath(new URL('../../', import.meta.url));
const require = createRequire(`${REPO}frontend/package.json`);
const { chromium } = require('@playwright/test');

const BASE = 'http://localhost:5173';
const EMAIL = 'admin@demo.local';
const PASSWORD = 'Demo-Admin-2026';
const OUT = `${REPO}docs/images/guide/`;
mkdirSync(OUT, { recursive: true });
const LIVE = { en: 'Live', fr: 'Connecté', km: 'បានភ្ជាប់' };
const DESKTOP = { viewport: { width: 1440, height: 900 } };

const browser = await chromium.launch({ channel: 'chrome' });

async function session(lang) {
  const ctx = await browser.newContext({ ...DESKTOP, baseURL: BASE, deviceScaleFactor: 1, locale: 'en-GB', timezoneId: 'Asia/Phnom_Penh' });
  const page = await ctx.newPage();
  const r = await page.request.post('/api/v1/auth/login', { data: { email: EMAIL, password: PASSWORD } });
  const me = await r.json();
  const headers = { 'X-CSRF-Token': me.csrf_token };
  const api = async (method, path, data) => (await page.request.fetch(`/api/v1${path}`, { method, data, headers })).json();
  await api('PATCH', '/auth/me', { preferred_language: lang });
  await page.goto('/');
  await page.evaluate((l) => localStorage.setItem('hms.language', l), lang);
  return { ctx, page, api, headers, hotel: me.hotels[0].id, lang };
}

async function shot(s, path, name) {
  await s.page.goto(path);
  await s.page.getByText(LIVE[s.lang], { exact: true }).first().waitFor({ timeout: 20_000 });
  await s.page.waitForLoadState('networkidle');
  await s.page.waitForTimeout(800);
  await s.page.screenshot({ path: `${OUT}${s.lang}-${name}.png` });
  console.log('shot', s.lang, name);
}

// The demo hotel's logo (shown in the header and on documents).
{
  const s = await session('en');
  const logos = await s.api('GET', `/hotels/${s.hotel}/media?owner_type=hotel`);
  if (!logos.length) {
    const r = await s.page.request.post(`/api/v1/hotels/${s.hotel}/media`, {
      headers: s.headers,
      multipart: { owner_type: 'hotel', file: { name: 'logo.png', mimeType: 'image/png', buffer: readFileSync(`${REPO}frontend/e2e/fixtures/logo.png`) } },
    });
    console.log('logo', r.status());
  }
  await s.ctx.close();
}

for (const lang of ['fr', 'en', 'km']) {
  // Sign-in page in that language.
  {
    const ctx = await browser.newContext({ ...DESKTOP, baseURL: BASE, deviceScaleFactor: 1, locale: 'en-GB' });
    const page = await ctx.newPage();
    await page.goto('/');
    await page.evaluate((l) => localStorage.setItem('hms.language', l), lang);
    await page.reload();
    await page.getByRole('button').first().waitFor();
    await page.waitForTimeout(600);
    await page.screenshot({ path: `${OUT}${lang}-login.png` });
    console.log('shot', lang, 'login');
    await ctx.close();
  }
  const s = await session(lang);
  const res = (await s.api('GET', `/hotels/${s.hotel}/reservations?q=Durand&limit=5`)).items[0];
  for (const [path, name] of [
    ['/', 'dashboard'],
    ['/calendar', 'calendar'],
    [`/reservations/${res.id}`, 'reservation'],
    ['/front-desk', 'front-desk'],
    ['/housekeeping', 'housekeeping'],
    ['/maintenance', 'maintenance'],
    ['/restaurant/floor', 'restaurant'],
    ['/vehicles/schedule', 'vehicles'],
    ['/pricing/calendar', 'pricing'],
    ['/night-audit', 'night-audit'],
    ['/settings/profile', 'settings'],
  ]) await shot(s, path, name);
  await s.api('PATCH', '/auth/me', { preferred_language: 'en' });
  await s.ctx.close();
}
await browser.close();
