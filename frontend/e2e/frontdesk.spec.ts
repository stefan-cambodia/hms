import { expect, type APIRequestContext, type Page, test } from '@playwright/test';

import { freeRoom, hotelDay } from './support';

const EMAIL = process.env.E2E_EMAIL ?? 'admin@demo.local';
const PASSWORD = process.env.E2E_PASSWORD ?? 'Demo-Admin-2026';
const SHOTS = 'e2e-results/screenshots';

interface Session {
  request: APIRequestContext;
  csrf: string;
  hotel: { id: string; timezone: string; currency_code: string };
}

/** Log in through the API (the browser context shares the cookie), for test data setup. */
async function apiLogin(page: Page): Promise<Session> {
  const r = await page.request.post('/api/v1/auth/login', { data: { email: EMAIL, password: PASSWORD } });
  expect(r.ok()).toBeTruthy();
  const me = await r.json();
  return { request: page.request, csrf: me.csrf_token, hotel: me.hotels[0] };
}

async function call<T = Record<string, unknown>>(s: Session, method: 'GET' | 'POST', path: string, data?: unknown): Promise<T> {
  const url = `/api/v1/hotels/${s.hotel.id}${path}`;
  const r = method === 'GET' ? await s.request.get(url) : await s.request.post(url, { data, headers: { 'X-CSRF-Token': s.csrf } });
  if (!r.ok()) throw new Error(`${method} ${path}: ${r.status()} ${await r.text()}`);
  return (await r.json()) as T;
}

/** A reservation arriving today in a free, clean room (see `freeRoom`). Created through the API. */
async function arrivalToday(s: Session, lastName: string, nights = 2): Promise<{ id: string; code: string; room: string }> {
  const room = await freeRoom(s, nights);
  const res = await call<{ id: string; code: string }>(s, 'POST', '/reservations', {
    arrival: hotelDay(s.hotel.timezone),
    departure: hotelDay(s.hotel.timezone, nights),
    guest: { first_name: 'Desk', last_name: lastName },
    rooms: [{ room_type_id: room.room_type_id, room_id: room.id, adults: 2 }],
    override_restrictions: true,
  });
  return { id: res.id, code: res.code, room: room.number };
}

async function openApp(page: Page, path: string) {
  await page.goto('/');
  await page.evaluate(() => localStorage.setItem('hms.language', 'en'));
  await page.goto(path);
  await expect(page.getByText('Live')).toBeVisible({ timeout: 15_000 });
}

test.describe.configure({ mode: 'serial' });

test('check-in, extras, payment in riel, early check-out with settlement, invoice PDF', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop', 'full flow checked once; tablets check the screens');
  const s = await apiLogin(page);
  const currencies = await call<{ code: string }[]>(s, 'GET', '/currencies');
  if (!currencies.some((c) => c.code === 'KHR')) await call(s, 'POST', '/currencies', { code: 'KHR', units_per_base: '4100' });
  const guest = `Flow${Date.now() % 100000}`;
  const res = await arrivalToday(s, guest);

  // Front desk: the arrival is listed and checked in from there.
  await openApp(page, '/front-desk');
  const row = page.locator(`[data-stay="${res.code}"]`);
  await expect(row).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/${info.project.name}-frontdesk-arrivals.png`, fullPage: true });
  await row.getByRole('button', { name: 'Check in' }).click();
  await expect(page.getByText(`${res.code} checked in`)).toBeVisible();
  await page.getByRole('tab', { name: /In house/ }).click();
  await expect(page.locator(`[data-stay="${res.code}"]`)).toBeVisible();

  // Folio: an extra item, then a partial payment in riel.
  await page.goto(`/reservations/${res.id}`);
  const folio = page.getByTestId('folio');
  await expect(folio).toBeVisible();
  await folio.getByRole('button', { name: 'Add charge' }).click();
  let dialog = page.getByRole('dialog');
  await dialog.getByLabel('Item').fill('Minibar');
  await dialog.getByLabel('Qty').fill('2');
  await dialog.getByLabel('Unit price').fill('8');
  await dialog.getByRole('button', { name: 'Post charge' }).click();
  await expect(page.getByText('Charge posted', { exact: true })).toBeVisible();
  await expect(folio.locator('[data-charge="service"]')).toContainText('$16.00');

  await folio.getByRole('button', { name: 'Take payment' }).click();
  dialog = page.getByRole('dialog');
  await dialog.getByRole('textbox', { name: 'Currency' }).click();
  await page.getByRole('option', { name: 'KHR' }).click();
  await dialog.getByLabel('Amount').fill('41000');
  await expect(dialog.getByTestId('conversion')).toContainText('$10.00');
  await dialog.getByRole('button', { name: 'Record payment' }).click();
  await expect(page.getByText(/Payment RC-\d+ recorded/)).toBeVisible();
  await expect(folio.locator('[data-payment]').first()).toContainText('$10.00');
  await page.screenshot({ path: `${SHOTS}/${info.project.name}-folio.png`, fullPage: true });

  // Check-out today: an early departure (1 night released), then the balance must be settled.
  await page.getByRole('button', { name: 'Check out' }).first().click();
  await expect(page.getByText('Early departure')).toBeVisible();
  await page.getByRole('button', { name: 'Release and check out' }).click();
  await expect(page.getByText('Balance due')).toBeVisible();
  await page.getByRole('button', { name: /Take payment \(/ }).click();
  dialog = page.getByRole('dialog', { name: 'Take payment' });
  await dialog.getByRole('button', { name: 'Record payment' }).click();
  await expect(page.getByText(`${res.code} checked out`)).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText('Checked out', { exact: true }).first()).toBeVisible();
  await expect(page.getByTestId('folio-balance')).toContainText('$0.00');

  // Invoice: issued with the next number, downloadable as a PDF.
  await folio.getByRole('button', { name: 'Issue invoice' }).click();
  dialog = page.getByRole('dialog');
  await dialog.getByRole('button', { name: 'Issue invoice' }).click();
  await expect(page.getByText(/^Invoice INV-\d+ issued$/)).toBeVisible();
  const pdfLink = folio.locator('[data-invoice] a', { hasText: 'PDF' });
  const href = await pdfLink.getAttribute('href');
  const pdf = await page.request.get(href!);
  expect(pdf.headers()['content-type']).toBe('application/pdf');
  expect((await pdf.body()).subarray(0, 5).toString()).toBe('%PDF-');
  await page.screenshot({ path: `${SHOTS}/${info.project.name}-checked-out.png`, fullPage: true });

  // Cash-up report lists the riel payment separately.
  await page.goto('/billing/payments');
  await expect(page.getByTestId('payment-summary')).toContainText('KHR');
  await page.screenshot({ path: `${SHOTS}/${info.project.name}-billing.png`, fullPage: true });
});

test('cancelling inside the penalty period charges the policy fee', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop', 'checked once');
  const s = await apiLogin(page);
  const res = await arrivalToday(s, `Cancel${Date.now() % 100000}`, 1);
  await openApp(page, `/reservations/${res.id}`);
  await page.getByRole('button', { name: 'Cancel reservation' }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByTestId('fee-preview')).toContainText('Cancellation fee');
  await dialog.getByLabel('Reason').fill('Flight cancelled');
  await dialog.getByRole('button', { name: 'Cancel reservation' }).click();
  await expect(page.getByTestId('folio')).toContainText('Cancellation fee');
  await expect(page.getByTestId('folio-balance')).not.toContainText('$0.00');
});

test('front desk and room board on every device', async ({ page }, info) => {
  await apiLogin(page);
  await openApp(page, '/front-desk?tab=rooms');
  await expect(page.locator('[data-room-tile]').first()).toBeVisible();
  await page.waitForLoadState('networkidle');
  await page.screenshot({ path: `${SHOTS}/${info.project.name}-room-board.png`, fullPage: true });
  await page.getByRole('tab', { name: /In house/ }).click();
  await page.screenshot({ path: `${SHOTS}/${info.project.name}-in-house.png`, fullPage: true });
});
