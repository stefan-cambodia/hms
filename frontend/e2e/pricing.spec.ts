import { expect, type Page, test } from '@playwright/test';

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

// A private two-week window far ahead for this run.
const START = (() => {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() + 500 + (Math.floor(Date.now() / 1000) % 300));
  return d.toISOString().slice(0, 10);
})();

test.describe.configure({ mode: 'serial' });

test('rate calendar, plans and rules render', async ({ page }, info) => {
  await login(page);
  await page.goto('/pricing/calendar');
  await expect(page.locator('[data-rate-cell]').first()).toBeVisible();
  await page.waitForLoadState('networkidle');
  await page.screenshot({ path: `${SHOTS}/${info.project.name}-pricing-calendar.png`, fullPage: true });
  await page.goto('/pricing/plans');
  await expect(page.getByRole('cell', { name: /Non-refundable saver/ })).toBeVisible();
  await expect(page.getByText(/Best available rate −10 %/)).toBeVisible();
  await page.goto('/pricing/rules');
  await expect(page.getByText('High season')).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/${info.project.name}-pricing-rules.png`, fullPage: true });
});

test('set a price from the rate calendar and see it in a new reservation', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop', 'editing flow checked once');
  await login(page);
  await page.goto(`/pricing/calendar?start=${START}`);
  const row = page.locator('[data-rate-row="STD-DBL"]');
  const cell = row.locator(`[data-rate-cell="${START}"]`);
  await cell.click();
  const drawer = page.getByRole('dialog');
  await expect(drawer.getByText('Edit rates')).toBeVisible();
  await drawer.locator('label', { hasText: /^Set price$/ }).click();
  await drawer.getByLabel('New price per night').fill('77');
  await drawer.getByRole('button', { name: 'Apply' }).click();
  await expect(page.getByText('1 rate updated')).toBeVisible();
  await expect(cell).toContainText('$77.00');

  // The new price and the derived rates show up when booking that night.
  await page.goto(`/calendar?view=week&start=${START}`);
  const track = page.locator('[data-room-number="103"] [data-drop-row]');
  await track.scrollIntoViewIfNeeded();
  const box = (await track.boundingBox())!;
  await page.mouse.click(box.x + box.width / 14, box.y + box.height / 2);
  const drawer2 = page.getByRole('dialog');
  await drawer2.getByLabel('First name').fill('Rate');
  await drawer2.getByLabel('Last name').fill(`Check${Date.now() % 10000}`);
  await expect(drawer2.getByText('$77.00').first()).toBeVisible({ timeout: 10_000 });
  await drawer2.getByRole('textbox', { name: 'Rate' }).click();
  await expect(page.getByRole('option', { name: /Non-refundable saver · \$69\.30/ })).toBeVisible();
  await page.getByRole('option', { name: /Bed & breakfast · \$93\.00/ }).click();
  await expect(drawer2.getByText('$93.00').first()).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/new-reservation-rates.png` });
  await drawer2.getByRole('button', { name: 'Create reservation' }).click();
  await expect(page.getByText(/Reservation R\d+ created/)).toBeVisible();
});
