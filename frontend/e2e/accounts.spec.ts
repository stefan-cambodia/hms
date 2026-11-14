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

async function apiLogin(page: Page): Promise<Session> {
  const r = await page.request.post('/api/v1/auth/login', { data: { email: EMAIL, password: PASSWORD } });
  expect(r.ok()).toBeTruthy();
  const me = await r.json();
  return { request: page.request, csrf: me.csrf_token, hotel: me.hotels[0] };
}

async function call<T = Record<string, unknown>>(s: Session, method: 'GET' | 'POST' | 'PATCH', path: string, data?: unknown): Promise<T> {
  const url = `/api/v1/hotels/${s.hotel.id}${path}`;
  const headers = { 'X-CSRF-Token': s.csrf };
  const r = method === 'GET' ? await s.request.get(url) : await s.request.fetch(url, { method, data, headers });
  if (!r.ok()) throw new Error(`${method} ${path}: ${r.status()} ${await r.text()}`);
  return (await r.json()) as T;
}

async function openApp(page: Page, path: string) {
  await page.goto('/');
  await page.evaluate(() => localStorage.setItem('hms.language', 'en'));
  await page.goto(path);
  await expect(page.getByText('Live')).toBeVisible({ timeout: 15_000 });
}

test.describe.configure({ mode: 'serial' });

test('direct billing: transfer to the company at departure, the company pays, statement PDF', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop', 'workflow checked once; tablets check the screens');
  const s = await apiLogin(page);
  const suffix = `${Date.now() % 100000}`;
  const company = `Angkor Travel ${suffix}`;
  const acc = await call<{ id: string }>(s, 'POST', '/company-accounts', {
    code: `ANGKOR${suffix}`,
    name: company,
    legal_name: `${company} Co., Ltd.`,
    tax_id: `K009-${suffix}`,
    city: 'Siem Reap',
    country_code: 'KH',
    payment_terms_days: 15,
  });
  const room = await freeRoom(s, 1);
  const res = await call<{ id: string; code: string; version: number }>(s, 'POST', '/reservations', {
    arrival: hotelDay(s.hotel.timezone),
    departure: hotelDay(s.hotel.timezone, 1),
    guest: { first_name: 'Corporate', last_name: `Guest${suffix}` },
    rooms: [{ room_type_id: room.room_type_id, room_id: room.id, adults: 1 }],
    override_restrictions: true,
  });

  // The booking is authorised for direct billing from its edit form.
  await openApp(page, `/reservations/${res.id}`);
  await page.getByRole('button', { name: 'Edit details' }).click();
  const form = page.getByRole('dialog');
  await form.getByRole('textbox', { name: 'Direct billing' }).click();
  await page.getByRole('option', { name: new RegExp(company) }).click();
  await form.getByRole('button', { name: 'Save' }).click();
  await expect(page.getByTestId('billed-to')).toContainText(company);

  // Its balance goes to the company: the invoice is made out to it, the folio is settled.
  const folio = page.getByTestId('folio');
  await folio.getByTestId('transfer-to-company').click();
  await page.getByRole('dialog').getByRole('button', { name: 'Transfer' }).click();
  await expect(page.getByText(`Transferred to ${company}`)).toBeVisible();
  await expect(folio.getByTestId('folio-balance')).toContainText('$0.00');
  await expect(folio).toContainText('Company account');
  await page.screenshot({ path: `${SHOTS}/${info.project.name}-folio-transferred.png`, fullPage: true });

  // The company's account: one open invoice, then its bank transfer settles it.
  await openApp(page, '/accounts');
  await page.locator(`[data-account="ANGKOR${suffix}"]`).click();
  const detail = page.getByTestId('account-detail');
  await expect(detail.getByTestId('account-items')).toContainText(res.code);
  const owed = (await detail.getByTestId('account-balance').innerText()).trim();
  expect(owed).not.toBe('$0.00');
  await page.screenshot({ path: `${SHOTS}/${info.project.name}-company-account.png`, fullPage: true });
  await detail.getByRole('button', { name: 'Record a payment' }).click();
  const pay = page.getByRole('dialog', { name: new RegExp(`Payment from ${company}`) });
  await pay.getByLabel('Reference').fill(`ABA ${suffix}`);
  await pay.getByRole('button', { name: 'Record a payment' }).click();
  await expect(page.getByText('Payment recorded')).toBeVisible();
  await expect(detail.getByTestId('account-balance')).toHaveText('$0.00');
  await expect(detail.getByTestId('account-items')).toContainText('Paid');

  const pdf = await page.request.get(`/api/v1/hotels/${s.hotel.id}/company-accounts/${acc.id}/statement.pdf`);
  expect(pdf.headers()['content-type']).toBe('application/pdf');
});

test('split bill: the company pays the room, the guest the extras', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop', 'workflow checked once; tablets check the screens');
  const s = await apiLogin(page);
  const suffix = `${Date.now() % 100000}`;
  const company = `Mekong Tours ${suffix}`;
  await call(s, 'POST', '/company-accounts', { code: `MEKONG${suffix}`, name: company, city: 'Phnom Penh', country_code: 'KH' });
  const room = await freeRoom(s, 1);
  const res = await call<{ id: string; version: number }>(s, 'POST', '/reservations', {
    arrival: hotelDay(s.hotel.timezone),
    departure: hotelDay(s.hotel.timezone, 1),
    guest: { first_name: 'Split', last_name: `Guest${suffix}` },
    rooms: [{ room_type_id: room.room_type_id, room_id: room.id, adults: 1 }],
    override_restrictions: true,
  });
  await call(s, 'POST', `/reservations/${res.id}/charges`, { description: 'Minibar', unit_price: '6.00' });

  // Billed to the company, which pays the room only.
  await openApp(page, `/reservations/${res.id}`);
  await page.getByRole('button', { name: 'Edit details' }).click();
  const form = page.getByRole('dialog');
  await form.getByRole('textbox', { name: 'Direct billing' }).click();
  await page.getByRole('option', { name: new RegExp(company) }).click();
  await form.getByText('The room only').click();
  await form.getByRole('button', { name: 'Save' }).click();
  await expect(page.getByTestId('billed-to')).toContainText(`Room billed to ${company}`);

  // Two parts: the nights for the company, the minibar for the guest.
  const folio = page.getByTestId('folio');
  await expect(folio.getByTestId('folio-parts')).toBeVisible();
  const minibar = folio.locator('tr', { hasText: 'Minibar' });
  await expect(minibar.locator('[data-part="guest"]')).toBeVisible();
  await minibar.getByRole('button', { name: `Move to ${company}’s bill` }).click();
  await expect(minibar.locator('[data-part="company"]')).toBeVisible();
  await minibar.getByRole('button', { name: 'Move to the guest’s bill' }).click();
  await expect(minibar.locator('[data-part="guest"]')).toBeVisible();

  // The guest pays their part, the company's part goes to its account.
  await folio.getByRole('button', { name: 'Take payment' }).click();
  const pay = page.getByRole('dialog');
  await expect(pay.getByTestId('payment-part')).toBeVisible();
  await pay.getByRole('button', { name: 'Record payment' }).click();
  await expect(folio.getByTestId('part-guest-balance')).toContainText('$0.00');
  await folio.getByTestId('transfer-to-company').click();
  await page.getByRole('dialog').getByRole('button', { name: 'Transfer' }).click();
  await expect(folio.getByTestId('part-company-balance')).toContainText('$0.00');
  await expect(folio.getByTestId('folio-balance')).toContainText('$0.00');

  // The guest's own invoice (the company's was made out with the transfer).
  await folio.getByRole('button', { name: 'Issue invoice' }).click();
  const invoice = page.getByRole('dialog');
  await expect(invoice.getByTestId('invoice-part')).toBeVisible();
  await invoice.getByRole('button', { name: 'Issue invoice' }).click();
  await expect(folio.locator('[data-invoice]')).toHaveCount(2);
  await expect(folio.locator('[data-invoice] [data-part="company"]')).toBeVisible();
  await expect(folio.locator('[data-invoice] [data-part="guest"]')).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/${info.project.name}-split-folio.png`, fullPage: true });
});

test('company accounts screen on every device', async ({ page }, info) => {
  await apiLogin(page);
  await openApp(page, '/accounts');
  await expect(page.getByRole('heading', { level: 1, name: 'Company accounts' })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/${info.project.name}-accounts.png` });
});
