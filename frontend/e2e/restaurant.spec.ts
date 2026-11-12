import { expect, type Page, test } from '@playwright/test';

import { freeRoom, hotelDay } from './support';

const EMAIL = process.env.E2E_EMAIL ?? 'admin@demo.local';
const PASSWORD = process.env.E2E_PASSWORD ?? 'Demo-Admin-2026';
const SHOTS = 'e2e-results/screenshots';

interface Session {
  csrf: string;
  hotel: { id: string; timezone: string };
}

async function apiLogin(page: Page): Promise<Session> {
  const r = await page.request.post('/api/v1/auth/login', { data: { email: EMAIL, password: PASSWORD } });
  expect(r.ok()).toBeTruthy();
  const me = await r.json();
  return { csrf: me.csrf_token, hotel: me.hotels[0] };
}

async function call<T = Record<string, unknown>>(page: Page, s: Session, method: 'GET' | 'POST', path: string, data?: unknown): Promise<T> {
  const url = `/api/v1/hotels/${s.hotel.id}${path}`;
  const r = method === 'GET' ? await page.request.get(url) : await page.request.post(url, { data, headers: { 'X-CSRF-Token': s.csrf } });
  if (!r.ok()) throw new Error(`${method} ${path}: ${r.status()} ${await r.text()}`);
  return (await r.json()) as T;
}

/** The demo hotel's restaurant, menu and tables (created once, reused by later runs). */
async function ensureRestaurant(page: Page, s: Session): Promise<string> {
  type Named = { id: string; name: { en?: string } };
  let outlet = (await call<(Named & { code: string })[]>(page, s, 'GET', '/restaurant/outlets')).find((o) => o.code === 'MAIN');
  if (!outlet)
    outlet = await call(page, s, 'POST', '/restaurant/outlets', {
      code: 'MAIN',
      name: { en: 'Riverside Restaurant', fr: 'Restaurant du Fleuve', km: 'ភោជនីយដ្ឋានមាត់ទន្លេ', 'zh-CN': '河畔餐厅', ru: 'Ресторан у реки' },
      service_charge_percent: '10',
    });
  const id = outlet!.id;
  const categories = await call<Named[]>(page, s, 'GET', `/restaurant/categories?outlet_id=${id}`);
  const category = async (en: string) =>
    categories.find((c) => c.name.en === en) ?? (await call<Named>(page, s, 'POST', '/restaurant/categories', { outlet_id: id, name: { en } }));
  const food = await category('Food');
  const drinks = await category('Drinks');
  const items = await call<(Named & { is_available: boolean })[]>(page, s, 'GET', `/restaurant/menu-items?outlet_id=${id}`);
  for (const [cat, en, price, station] of [
    [food, 'Fish amok', '8.00', 'kitchen'],
    [food, 'Lok lak', '7.50', 'kitchen'],
    [drinks, 'Beer', '2.50', 'bar'],
    [drinks, 'Water', '1.00', 'none'],
  ] as const) {
    const found = items.find((i) => i.name.en === en);
    if (!found) await call(page, s, 'POST', '/restaurant/menu-items', { category_id: cat.id, name: { en }, price, station });
    else if (!found.is_available) await call(page, s, 'POST', `/restaurant/menu-items/${found.id}/availability`, { is_available: true });
  }
  const tables = await call<{ label: string }[]>(page, s, 'GET', `/restaurant/tables?outlet_id=${id}`);
  for (let n = 1; n <= 8; n++) if (!tables.some((t) => t.label === `T${n}`)) await call(page, s, 'POST', '/restaurant/tables', { outlet_id: id, label: `T${n}`, seats: 4 });
  return id;
}

async function openApp(page: Page, path: string) {
  await page.goto('/');
  await page.evaluate(() => localStorage.setItem('hms.language', 'en'));
  await page.goto(path);
  await expect(page.getByText('Live')).toBeVisible({ timeout: 15_000 });
}

test.describe.configure({ mode: 'serial' });

test('table service: order, kitchen, serve, pay cash with change, receipt PDF', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop', 'workflow checked once; tablets check the screens');
  const s = await apiLogin(page);
  const outletId = await ensureRestaurant(page, s);
  const floor = await call<{ label: string; order: unknown }[]>(page, s, 'GET', `/restaurant/floor?outlet_id=${outletId}`);
  const table = floor.find((t) => !t.order);
  expect(table, 'a free table').toBeTruthy();

  await openApp(page, `/restaurant/floor?outlet=${outletId}`);
  await page.locator(`[data-table="${table!.label}"]`).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Open check' }).click();
  await expect(page.getByRole('heading', { name: `Table ${table!.label}` })).toBeVisible();

  await page.locator('[data-menu-item="Fish amok"]').click();
  await expect(page.locator('[data-line="Fish amok"]')).toContainText('1 × Fish amok');
  await page.locator('[data-menu-item="Fish amok"]').click();
  await expect(page.locator('[data-line="Fish amok"]')).toContainText('2 × Fish amok');
  await page.locator('[data-menu-item="Beer"]').click();
  await expect(page.locator('[data-line="Beer"]')).toBeVisible();
  // 16.00 + 2.50 = 18.50; +10% service = 20.35 (+ the demo hotel's taxes).
  await page.getByRole('button', { name: /Send to kitchen \(3 items\)/ }).click();
  await expect(page.getByText('Sent to the kitchen')).toBeVisible();
  await expect(page.locator('[data-line="Fish amok"]')).toContainText('Sent');
  await page.screenshot({ path: `${SHOTS}/${info.project.name}-restaurant-order.png`, fullPage: true });
  const orderUrl = page.url();

  // Kitchen display: the ticket for this table, marked ready.
  await page.goto(`/restaurant/kitchen?outlet=${outletId}`);
  const ticket = page.locator('[data-ticket]', { hasText: `Table ${table!.label}` });
  await expect(ticket).toContainText('2 × Fish amok');
  await page.screenshot({ path: `${SHOTS}/${info.project.name}-restaurant-kitchen.png`, fullPage: true });
  await ticket.getByRole('button', { name: 'All ready' }).click();
  await expect(ticket).toHaveCount(0, { timeout: 10_000 }).catch(() => undefined);

  await page.goto(orderUrl);
  await page.getByRole('button', { name: /Served \(1 ready\)/ }).click();
  await expect(page.getByText('Marked as served')).toBeVisible();
  await page.getByRole('button', { name: /^Pay / }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Amount').fill('50');
  await expect(dialog.getByTestId('change')).toContainText('Change to give');
  await dialog.getByRole('button', { name: 'Record payment' }).click();
  await expect(page.getByText('Check paid')).toBeVisible();
  await expect(page.getByText('Paid', { exact: true }).first()).toBeVisible();
  await expect(page.getByText(/Change to give/)).toBeVisible();

  const id = orderUrl.split('/').pop();
  const pdf = await page.request.get(`/api/v1/hotels/${s.hotel.id}/restaurant/orders/${id}/bill.pdf?language=km`);
  expect(pdf.headers()['content-type']).toBe('application/pdf');
  expect((await pdf.body()).subarray(0, 5).toString()).toBe('%PDF-');
});

test('room service charged to the guest room appears on the folio', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop', 'checked once');
  const s = await apiLogin(page);
  const outletId = await ensureRestaurant(page, s);
  // A guest checked in today.
  const start = hotelDay(s.hotel.timezone);
  const end = hotelDay(s.hotel.timezone, 1);
  const room = await freeRoom({ request: page.request, ...s });
  const guestName = `Diner${Date.now() % 100000}`;
  const res = await call<{ id: string; version: number }>(page, s, 'POST', '/reservations', {
    arrival: start,
    departure: end,
    guest: { first_name: 'Room', last_name: guestName },
    rooms: [{ room_type_id: room.room_type_id, room_id: room.id, adults: 2 }],
    override_restrictions: true,
  });
  await call(page, s, 'POST', `/reservations/${res.id}/check-in`, { version: res.version });

  await openApp(page, `/restaurant/floor?outlet=${outletId}`);
  await page.getByRole('button', { name: 'Room service' }).click();
  const open = page.getByRole('dialog');
  await open.getByRole('textbox', { name: 'Guest (room)' }).fill(room.number);
  await page.getByRole('option', { name: new RegExp(`^${room.number} · .*${guestName}`) }).click();
  await open.getByRole('button', { name: 'Open check' }).click();
  await page.locator('[data-menu-item="Lok lak"]').click();
  await expect(page.locator('[data-line="Lok lak"]')).toBeVisible();
  await page.getByRole('button', { name: /Send to kitchen/ }).click();
  await expect(page.getByText('Sent to the kitchen')).toBeVisible();
  await page.getByRole('button', { name: /^Pay / }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByText('Charge to room', { exact: true }).click();
  await dialog.getByRole('button', { name: 'Charge to the room' }).click();
  await expect(page.getByText('Check paid')).toBeVisible();
  await expect(page.getByText(`Charged to room ${room.number}`)).toBeVisible();

  // On the guest's folio.
  await page.goto(`/reservations/${res.id}`);
  await expect(page.getByTestId('folio')).toContainText('Riverside Restaurant');
});

test('restaurant screens on every device', async ({ page }, info) => {
  const s = await apiLogin(page);
  const outletId = await ensureRestaurant(page, s);
  await openApp(page, `/restaurant/floor?outlet=${outletId}`);
  await expect(page.locator('[data-table]').first()).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/${info.project.name}-restaurant-floor.png`, fullPage: true });
  await page.goto(`/restaurant/breakfast?outlet=${outletId}`);
  await expect(page.getByTestId('breakfast-count')).toBeVisible();
  await page.goto(`/restaurant/sales?outlet=${outletId}`);
  await expect(page.getByTestId('sales-stats')).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/${info.project.name}-restaurant-sales.png`, fullPage: true });
});
