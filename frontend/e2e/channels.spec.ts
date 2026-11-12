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

/** Remove connections left by earlier runs (the demo hotel is shared). */
async function removeConnections(page: Page, s: Session) {
  const base = `/api/v1/hotels/${s.hotel.id}/channel-connections`;
  for (const c of (await (await page.request.get(base)).json()) as { id: string }[]) {
    await page.request.delete(`${base}/${c.id}`, { headers: { 'X-CSRF-Token': s.csrf } });
  }
}

async function openApp(page: Page, path: string) {
  await page.goto('/');
  await page.evaluate(() => localStorage.setItem('hms.language', 'en'));
  await page.goto(path);
  await expect(page.getByText('Live')).toBeVisible({ timeout: 15_000 });
}

test.describe.configure({ mode: 'serial' });

test('channel manager: explanation, connection form, mapping (no call to the provider)', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop', 'workflow checked once; tablets check the screen');
  const s = await apiLogin(page);
  await removeConnections(page, s);

  await openApp(page, '/channels');
  await expect(page.getByTestId('no-channel')).toContainText('SiteMinder');
  await page.screenshot({ path: `${SHOTS}/${info.project.name}-channels-empty.png`, fullPage: true });

  // Sending and receiving are switched off: the test never contacts SiteMinder.
  await page.getByRole('button', { name: 'Add connection' }).click();
  const drawer = page.getByRole('dialog');
  await drawer.getByLabel('PMS code').fill('E2ETEST');
  await drawer.getByLabel('Hotel code').fill('E2EHOTEL');
  await drawer.getByLabel('Username').fill('e2e-user');
  await drawer.getByLabel('Password').fill('E2e-not-a-real-password');
  await drawer.getByLabel('Send availability, prices and restrictions', { exact: true }).uncheck();
  await expect(drawer.getByRole('switch', { name: 'Send availability, prices and restrictions', exact: true })).not.toBeChecked();
  await expect(drawer.getByRole('switch', { name: /^Receive reservations/ })).not.toBeChecked();
  await drawer.getByRole('button', { name: 'Save' }).click();
  await expect(page.getByText('Connection saved')).toBeVisible();

  const card = page.getByTestId('channel-connection');
  await expect(card).toContainText('Not verified');
  await expect(card).toContainText('E2EHOTEL');

  // Mapping: the first room type and its first rate plan.
  const roomInput = page.locator('[data-room-code]').first();
  await roomInput.fill('E2EROOM');
  const rateInput = page.locator('[data-rate-code]').first();
  await expect(rateInput).toBeEnabled();
  await rateInput.fill('E2ERATE');
  await page.getByRole('button', { name: 'Save mapping' }).click();
  await expect(page.getByText(/Mapping saved/)).toBeVisible();
  await page.reload();
  await expect(page.locator('[data-room-code]').first()).toHaveValue('E2EROOM');
  await page.screenshot({ path: `${SHOTS}/${info.project.name}-channels-mapping.png`, fullPage: true });

  await page.getByRole('tab', { name: /Received bookings/ }).click();
  await expect(page.getByText('No booking received yet')).toBeVisible();
  await page.getByRole('tab', { name: 'Activity log' }).click();
  await expect(page.getByText('No exchange yet')).toBeVisible();

  // Clean up through the UI.
  await card.getByRole('button', { name: 'Delete' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Delete' }).click();
  await expect(page.getByTestId('no-channel')).toBeVisible();
});

test('channel manager screen on every device', async ({ page }, info) => {
  await apiLogin(page);
  await openApp(page, '/channels');
  await expect(page.getByRole('heading', { level: 1, name: 'Channel manager' })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/${info.project.name}-channels.png`, fullPage: true });
});
