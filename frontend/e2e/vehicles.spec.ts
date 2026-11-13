import { expect, type Page, test } from '@playwright/test';

const EMAIL = process.env.E2E_EMAIL ?? 'admin@demo.local';
const PASSWORD = process.env.E2E_PASSWORD ?? 'Demo-Admin-2026';
const SHOTS = 'e2e-results/screenshots';

interface Session {
  csrf: string;
  hotel: { id: string };
}

async function apiLogin(page: Page): Promise<Session> {
  const r = await page.request.post('/api/v1/auth/login', { data: { email: EMAIL, password: PASSWORD } });
  expect(r.ok()).toBeTruthy();
  const me = await r.json();
  return { csrf: me.csrf_token, hotel: me.hotels[0] };
}

/** The demo hotel's fleet (created once, reused by later runs). */
async function ensureFleet(page: Page, s: Session) {
  const base = `/api/v1/hotels/${s.hotel.id}/vehicles`;
  const fleet = (await (await page.request.get(base)).json()) as { code: string }[];
  const wanted = [
    { code: 'SC-01', kind: 'scooter', make: 'Honda', model: 'Scoopy', plate: '1A-2041', daily_rate: '10', hourly_rate: '2', deposit_amount: '50', odometer: 12000 },
    { code: 'SC-02', kind: 'scooter', make: 'Honda', model: 'Click', plate: '1A-2042', daily_rate: '10', hourly_rate: '2', deposit_amount: '50', odometer: 8000 },
    { code: 'SC-03', kind: 'scooter', make: 'Yamaha', model: 'NMAX', plate: '1A-2043', daily_rate: '14', hourly_rate: '3', deposit_amount: '80', odometer: 5000 },
    { code: 'CAR-01', kind: 'car', make: 'Toyota', model: 'Camry', plate: '2B-7788', daily_rate: '45', driver_daily_rate: '25', seats: 4, deposit_amount: '200' },
    { code: 'BK-01', kind: 'bicycle', daily_rate: '3' },
  ];
  for (const v of wanted)
    if (!fleet.some((f) => f.code === v.code)) {
      const r = await page.request.post(base, { data: v, headers: { 'X-CSRF-Token': s.csrf } });
      expect(r.ok(), await r.text()).toBeTruthy();
    }
}

async function openApp(page: Page, path: string) {
  await page.goto('/');
  await page.evaluate(() => localStorage.setItem('hms.language', 'en'));
  await page.goto(path);
  await expect(page.getByText('Live')).toBeVisible({ timeout: 15_000 });
}

test.describe.configure({ mode: 'serial' });

test('rent a scooter: book, hand over with licence, take back, pay cash, contract PDF', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop', 'workflow checked once; tablets check the screens');
  const s = await apiLogin(page);
  await ensureFleet(page, s);
  // Scooters still out on an earlier rental (e.g. an interrupted run) cannot be handed over.
  const out = (await (await page.request.get(`/api/v1/hotels/${s.hotel.id}/vehicle-rentals?status=out`)).json()) as { vehicle_code: string }[];
  const away = new Set(out.map((r) => r.vehicle_code));
  const renter = `Rider${Date.now() % 100000}`;

  await openApp(page, '/vehicles/today');
  await page.getByRole('button', { name: 'New rental' }).click();
  const drawer = page.getByRole('dialog');
  await drawer.getByText('Other customer', { exact: true }).click();
  await drawer.getByLabel('First name').fill('Lena');
  await drawer.getByLabel('Last name').fill(renter);
  await drawer.getByRole('textbox', { name: 'Vehicle' }).click();
  // A scooter that is free for the period (others may be out from earlier runs).
  const here = ['SC-01', 'SC-02', 'SC-03'].filter((code) => !away.has(code));
  const option = page
    .getByRole('option', { name: new RegExp(`^(${here.join('|')}) · Scooter`) })
    .and(page.locator(':not([data-combobox-disabled])'))
    .first();
  await option.click();
  await expect(drawer.getByTestId('rental-quote')).toContainText('24 h');
  await drawer.getByRole('button', { name: 'Book' }).click();
  await expect(page.getByText(/Rental RNT-\d+ booked/)).toBeVisible();

  const detail = page.getByTestId('rental-detail');
  await expect(detail).toContainText(`Lena ${renter}`);
  await detail.locator('[data-action="pickup"]').click();
  let modal = page.getByRole('dialog', { name: 'Hand over' });
  await modal.getByLabel('Driving licence number').fill('KH-778899');
  await modal.getByRole('button', { name: 'Hand over' }).click();
  await expect(page.getByText('Vehicle handed over')).toBeVisible();
  await expect(detail).toContainText('Out');
  await expect(detail).toContainText('licence ••••8899');
  await page.screenshot({ path: `${SHOTS}/${info.project.name}-rental-out.png`, fullPage: true });

  await detail.locator('[data-action="return"]').click();
  modal = page.getByRole('dialog', { name: 'Take back' });
  const odometer = modal.getByLabel('Odometer');
  const km = Number((await odometer.inputValue()).replace(/\D/g, ''));
  await odometer.fill(String(km + 37));
  await modal.getByRole('button', { name: 'Take back' }).click();
  await expect(page.getByText(/Vehicle returned/)).toBeVisible();
  await expect(detail).toContainText('Returned');

  await detail.getByRole('button', { name: /^Pay / }).click();
  const pay = page.getByRole('dialog', { name: /Payment/ });
  await pay.getByLabel('Amount').fill('20');
  await expect(pay.getByTestId('change')).toBeVisible();
  await pay.getByRole('button', { name: 'Record payment' }).click();
  await expect(page.getByText(/Change to give/)).toBeVisible();
  await expect(detail.getByTestId('rental-balance')).toContainText('$0.00');

  const rentalId = new URL(page.url()).searchParams.get('rental');
  const pdf = await page.request.get(`/api/v1/hotels/${s.hotel.id}/vehicle-rentals/${rentalId}/contract.pdf?language=km`);
  expect(pdf.headers()['content-type']).toBe('application/pdf');
});

test('vehicle rental screens on every device', async ({ page }, info) => {
  const s = await apiLogin(page);
  await ensureFleet(page, s);
  await openApp(page, '/vehicles/schedule');
  await expect(page.locator('[data-schedule-vehicle="SC-01"]')).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/${info.project.name}-vehicles-schedule.png`, fullPage: true });
  await page.goto('/vehicles/fleet');
  await expect(page.locator('[data-vehicle="CAR-01"]')).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/${info.project.name}-vehicles-fleet.png`, fullPage: true });
});
