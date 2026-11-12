import { expect, type Page, test } from '@playwright/test';

const EMAIL = process.env.E2E_EMAIL ?? 'admin@demo.local';
const PASSWORD = process.env.E2E_PASSWORD ?? 'Demo-Admin-2026';
const SHOTS = 'e2e-results/screenshots';

async function apiLogin(page: Page) {
  const r = await page.request.post('/api/v1/auth/login', { data: { email: EMAIL, password: PASSWORD } });
  expect(r.ok()).toBeTruthy();
}

async function openApp(page: Page, path: string) {
  await page.goto('/');
  await page.evaluate(() => localStorage.setItem('hms.language', 'en'));
  await page.goto(path);
  await expect(page.getByText('Live')).toBeVisible({ timeout: 15_000 });
}

test.describe.configure({ mode: 'serial' });

test('reports: KPIs, comparison, table view, CSV export, forecast', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop', 'workflow checked once; tablets check the screens');
  await apiLogin(page);
  await openApp(page, '/reports');
  const perf = page.getByTestId('performance');
  await expect(perf.getByTestId('kpi-occupancy')).toContainText('%');
  await expect(perf.getByTestId('kpi-adr')).toBeVisible();
  await expect(perf.getByTestId('kpi-revpar')).toBeVisible();
  await expect(perf.getByText('vs previous period').first()).toBeVisible();
  await expect(perf.getByRole('img', { name: 'Occupancy by night' })).toBeVisible();

  // Keyboard access to the chart values (tooltip on focus + arrows).
  await perf.getByRole('img', { name: 'Occupancy by night' }).focus();
  await page.keyboard.press('ArrowRight');
  await expect(perf.getByText('This period').last()).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/${info.project.name}-reports.png`, fullPage: true });

  // Table view carries every value of the chart.
  await perf.getByText('Table', { exact: true }).first().click();
  await expect(perf.getByTestId('daily-table')).toBeVisible();

  // CSV export: UTF-8 with BOM, English separators.
  const download = page.waitForEvent('download');
  await perf.getByRole('button', { name: 'Export (CSV)' }).click();
  await page.getByRole('menuitem', { name: 'Figures by night' }).click();
  const file = await download;
  const text = (await (await file.createReadStream()).toArray()).map(String).join('');
  expect(text.charCodeAt(0)).toBe(0xfeff);
  expect(text).toContain('Night,Rooms,Out of service,Available,Sold,Occupancy %');

  // Last month, compared with last year.
  await page.getByTestId('range-preset').click();
  await page.getByRole('option', { name: 'Last month' }).click();
  await page.getByRole('textbox', { name: 'Compare with' }).click();
  await page.getByRole('option', { name: 'Same period last year' }).click();
  await expect(perf.getByText(/compared with/)).toBeVisible();

  await page.getByRole('tab', { name: 'Forecast' }).click();
  const fc = page.getByTestId('forecast');
  await expect(fc.getByTestId('forecast-occupancy')).toContainText('%');
  await expect(fc.getByRole('img', { name: 'Occupancy on the books' })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/${info.project.name}-forecast.png`, fullPage: true });
});

test('dashboard figures and reports on every device', async ({ page }, info) => {
  await apiLogin(page);
  await openApp(page, '/');
  const today = page.getByTestId('today-panel');
  await expect(today.getByTestId('tonight-occupancy')).toContainText('%');
  await expect(today.getByTestId('arrivals')).toBeVisible();
  await expect(today.getByRole('img', { name: 'Next 14 nights' })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/${info.project.name}-dashboard-kpis.png`, fullPage: true });
  await page.goto('/reports');
  await expect(page.getByTestId('kpi-occupancy')).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/${info.project.name}-reports-device.png`, fullPage: true });
});
