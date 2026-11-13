import { expect, type Page, test } from '@playwright/test';

const EMAIL = process.env.E2E_EMAIL ?? 'admin@demo.local';
const PASSWORD = process.env.E2E_PASSWORD ?? 'Demo-Admin-2026';
const SHOTS = 'e2e-results/screenshots';

async function open(page: Page) {
  const r = await page.request.post('/api/v1/auth/login', { data: { email: EMAIL, password: PASSWORD } });
  expect(r.ok()).toBeTruthy();
  await page.goto('/');
  await page.evaluate(() => localStorage.setItem('hms.language', 'en'));
  await page.goto('/night-audit');
  await expect(page.getByRole('heading', { name: 'End of day', level: 1 })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId('day-report')).toBeVisible();
}

test('end of day: open items, figures, closing and the day report', async ({ page }, info) => {
  await open(page);
  const closeButton = page.getByRole('button', { name: 'Close the day' }).first();
  // On a server where today's closure is already done, the next day to close
  // is today, which is not over yet: the page says so.
  // No button at all once that day is closed (e.g. a second run on the same database).
  if (info.project.name === 'desktop' && (await closeButton.count()) > 0 && (await closeButton.isEnabled())) {
    await closeButton.click();
    const dialog = page.getByRole('dialog');
    const confirm = dialog.getByRole('button', { name: 'Close the day' });
    const accept = dialog.getByRole('checkbox');
    if (await accept.count()) {
      await expect(confirm).toBeDisabled(); // open items must be acknowledged
      await accept.check();
    }
    await dialog.getByLabel('Notes').fill('Closed by the end-to-end test');
    await confirm.click();
    await expect(page.getByText(/is closed$/)).toBeVisible();
    await expect(page.getByRole('link', { name: 'Day report (PDF)' })).toBeVisible();
    const pdf = await page.request.get((await page.getByRole('link', { name: 'Day report (PDF)' }).getAttribute('href'))!);
    expect(pdf.headers()['content-type']).toBe('application/pdf');
    await expect(page.getByTestId('closures')).toBeVisible();
  } else {
    await expect(page.getByText(/Ready to close|is not over|is closed$|earlier day is still open/).first()).toBeVisible();
  }
  await page.screenshot({ path: `${SHOTS}/${info.project.name}-night-audit.png`, fullPage: true });
});
