import { type BrowserContext, expect, type Page, test } from '@playwright/test';

const EMAIL = process.env.E2E_EMAIL ?? 'admin@demo.local';
const PASSWORD = process.env.E2E_PASSWORD ?? 'Demo-Admin-2026';
const SHOTS = 'e2e-results/screenshots';

async function login(page: Page) {
  await page.goto('/');
  await page.evaluate(() => localStorage.setItem('hms.language', 'en'));
  await page.reload();
  if (await page.getByLabel('Email').isVisible().catch(() => false)) {
    await page.getByLabel('Email').fill(EMAIL);
    await page.getByLabel('Password').fill(PASSWORD);
    await page.getByRole('button', { name: 'Sign in' }).click();
  }
  await expect(page.getByText('Live')).toBeVisible({ timeout: 15_000 });
}

test.describe.configure({ mode: 'serial' });

// Each run works in its own empty week far in the future, so runs never collide.
const RUN_START = (() => {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() + 200 + (Math.floor(Date.now() / 1000) % 300));
  return d.toISOString().slice(0, 10);
})();
const WEEK = `/calendar?view=week&start=${RUN_START}`;
const GUEST = `Run${Date.now() % 1_000_000}`;

test('calendar shows bookings, availability and blocks', async ({ page }, info) => {
  await login(page);
  await page.goto('/calendar');
  await expect(page.locator('[data-calendar-item="stay"]').first()).toBeVisible();
  await expect(page.locator('[data-calendar-item="block"]').first()).toBeVisible();
  await page.waitForLoadState('networkidle');
  await page.screenshot({ path: `${SHOTS}/${info.project.name}-calendar.png`, fullPage: false });
  await page.locator('label', { hasText: /^Month$/ }).click();
  await page.waitForLoadState('networkidle');
  await page.screenshot({ path: `${SHOTS}/${info.project.name}-calendar-month.png`, fullPage: false });
});

test('create a reservation from an empty calendar cell', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop', 'creation flow checked once');
  await login(page);
  await page.goto(WEEK);
  // The run's week is empty: click room 108 on the third day.
  const track = page.locator('[data-room-number="108"] [data-drop-row]');
  await track.scrollIntoViewIfNeeded();
  const box = (await track.boundingBox())!;
  await page.mouse.click(box.x + (box.width / 7) * 2.5, box.y + box.height / 2);
  const drawer = page.getByRole('dialog');
  await expect(drawer.getByText('New reservation')).toBeVisible();
  await drawer.getByLabel('First name').fill('Playwright');
  await drawer.getByLabel('Last name').fill(GUEST);
  await expect(drawer.getByText('Total')).toBeVisible({ timeout: 10_000 });
  await page.screenshot({ path: `${SHOTS}/new-reservation.png` });
  await drawer.getByRole('button', { name: 'Create reservation' }).click();
  await expect(page.getByText(/Reservation R\d+ created/)).toBeVisible();
  await expect(page.locator('[data-calendar-item="stay"]', { hasText: GUEST })).toBeVisible();
});

test('drag a booking to another room (with confirmation)', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop', 'mouse drag checked on desktop');
  await login(page);
  await page.goto(WEEK);
  const bar = page.locator('[data-calendar-item="stay"]', { hasText: GUEST }).first();
  const target = page.locator('[data-room-number="109"] [data-drop-row]');
  await target.scrollIntoViewIfNeeded();
  await expect(bar).toBeVisible();
  const from = (await bar.boundingBox())!;
  const to = (await target.boundingBox())!;
  await page.mouse.move(from.x + 20, from.y + from.height / 2);
  await page.mouse.down();
  await page.mouse.move(from.x + 30, from.y + from.height / 2, { steps: 3 });
  await page.mouse.move(from.x + 20, to.y + to.height / 2, { steps: 8 });
  await page.mouse.up();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByText(/room 109/)).toBeVisible();
  await dialog.getByRole('button', { name: 'Move' }).click();
  await expect(page.getByText(/moved/)).toBeVisible();
  const moved = page.locator('[data-room-number="109"] [data-drop-row]');
  await expect(moved.locator('[data-calendar-item="stay"]', { hasText: GUEST })).toBeVisible();
});

test('reservation detail: assign room and cancel', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop', 'detail flow checked once');
  await login(page);
  await page.goto('/reservations');
  await page.getByPlaceholder('Code, guest name, email or OTA reference').fill(GUEST);
  await page.getByRole('row', { name: new RegExp(GUEST) }).first().click();
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(/R\d+/);
  await page.waitForLoadState('networkidle');
  await page.screenshot({ path: `${SHOTS}/reservation-detail.png`, fullPage: true });
  await page.getByRole('textbox', { name: 'Room' }).click();
  await page.getByRole('option', { name: '111' }).click();
  await expect(page.getByText('Room assignment saved')).toBeVisible();
  await expect(page.getByText('Room: 109 → 111')).toBeVisible();
  await page.getByRole('button', { name: 'Cancel reservation' }).click();
  await page.getByLabel('Reason').fill('E2E test cleanup');
  await page.getByRole('dialog').getByRole('button', { name: 'Cancel reservation' }).click();
  await expect(page.getByText('Reservation cancelled; the room is available again')).toBeVisible();
  await expect(page.getByText(/Cancelled on/)).toBeVisible();
});

test('a booking made on one device appears on another calendar', async ({ browser }, info) => {
  test.skip(info.project.name !== 'desktop', 'sync checked once');
  const contexts: BrowserContext[] = [await browser.newContext(), await browser.newContext()];
  const [desk, tablet] = await Promise.all(contexts.map((c) => c.newPage()));
  await login(desk);
  await login(tablet);
  await tablet.goto('/calendar');
  await expect(tablet.locator('[data-calendar-item="stay"]').first()).toBeVisible();
  const name = `Sync${Date.now() % 100000}`;
  await desk.goto('/reservations');
  await desk.getByRole('button', { name: 'New reservation' }).click();
  const drawer = desk.getByRole('dialog');
  await drawer.getByLabel('First name').fill(name);
  await drawer.getByLabel('Last name').fill('Device');
  await drawer.getByRole('textbox', { name: 'Category' }).click();
  // Demo data is shared between runs: pick a category that is not sold out tonight.
  await expect(desk.getByRole('option', { name: / free$/ }).first()).toBeVisible();
  await desk.getByRole('option', { name: / free$/ }).filter({ hasNotText: / 0 free$/ }).first().click();
  await expect(drawer.getByText('Total')).toBeVisible({ timeout: 10_000 });
  await drawer.getByRole('button', { name: 'Create reservation' }).click();
  await expect(desk.getByRole('heading', { level: 1 })).toHaveText(/R\d+/);
  await expect(tablet.locator('[data-calendar-item="stay"]', { hasText: name })).toBeVisible({ timeout: 5_000 });
  await Promise.all(contexts.map((c) => c.close()));
});

test('tablet: long-press and drag a booking to another room', async ({ page }, info) => {
  test.skip(info.project.name !== 'android-tablet', 'touch drag is a tablet interaction');
  await login(page);
  // Create a booking in room 106 on a private week through the API.
  const me = await (await page.request.get('/api/v1/auth/me')).json();
  const hotelId = me.hotels[0].id;
  const headers = { 'X-CSRF-Token': me.csrf_token };
  const rooms = await (await page.request.get(`/api/v1/hotels/${hotelId}/rooms`)).json();
  const room = (n: string) => rooms.find((r: { number: string }) => r.number === n);
  const start = new Date(Date.now() + (400 + (Math.floor(Date.now() / 1000) % 200)) * 86_400_000).toISOString().slice(0, 10);
  const day2 = new Date(Date.parse(start) + 2 * 86_400_000).toISOString().slice(0, 10);
  const day3 = new Date(Date.parse(start) + 3 * 86_400_000).toISOString().slice(0, 10);
  const name = `Touch${Date.now() % 100000}`;
  const created = await page.request.post(`/api/v1/hotels/${hotelId}/reservations`, {
    headers,
    data: { arrival: day2, departure: day3, guest: { first_name: name, last_name: 'Tablet' }, rooms: [{ room_type_id: room('106').room_type_id, room_id: room('106').id, adults: 2 }] },
  });
  expect(created.status()).toBe(201);

  await page.goto(`/calendar?view=week&start=${start}`);
  const target = page.locator('[data-room-number="107"] [data-drop-row]');
  await target.scrollIntoViewIfNeeded();
  const bar = page.locator('[data-calendar-item="stay"]', { hasText: name });
  await expect(bar).toBeVisible();
  const from = (await bar.boundingBox())!;
  const to = (await target.boundingBox())!;

  const cdp = await page.context().newCDPSession(page);
  const touch = (type: string, x: number, y: number) =>
    cdp.send('Input.dispatchTouchEvent', { type, touchPoints: type === 'touchEnd' ? [] : [{ x, y }] });
  const x = from.x + Math.min(30, from.width / 2);
  await touch('touchStart', x, from.y + from.height / 2);
  await page.waitForTimeout(500); // long-press
  for (let i = 1; i <= 8; i++) await touch('touchMove', x, from.y + from.height / 2 + ((to.y - from.y) * i) / 8);
  await touch('touchEnd', x, to.y + to.height / 2);

  const dialog = page.getByRole('dialog');
  await expect(dialog.getByText(/room 107/)).toBeVisible();
  await dialog.getByRole('button', { name: 'Move' }).click();
  await expect(page.locator('[data-room-number="107"] [data-calendar-item="stay"]', { hasText: name })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/tablet-drag-done.png` });
});
