import { expect, type Page, test } from '@playwright/test';

const EMAIL = process.env.E2E_EMAIL ?? 'admin@demo.local';
const PASSWORD = process.env.E2E_PASSWORD ?? 'Demo-Admin-2026';
const SHOTS = 'e2e-results/screenshots';

async function apiLogin(page: Page) {
  const r = await page.request.post('/api/v1/auth/login', { data: { email: EMAIL, password: PASSWORD } });
  expect(r.ok()).toBeTruthy();
}

// The backup service runs only in installed stacks (deploy/docker-compose.yml);
// its backup and restore paths are exercised by deploy/tests/restore-drill.sh.
// Here: the screen, whichever situation the test server is in.
test('backups: status, list and the guarded restore dialog', async ({ page }, info) => {
  await apiLogin(page);
  await page.goto('/');
  await page.evaluate(() => localStorage.setItem('hms.language', 'en'));
  await page.goto('/backups');
  await expect(page.getByRole('heading', { name: 'Backups', level: 1 })).toBeVisible({ timeout: 15_000 });
  const table = page.getByTestId('backups-table');
  const notConnected = page.getByText('Backup service not connected');
  await expect(table.or(notConnected)).toBeVisible();
  if (await notConnected.isVisible()) {
    await expect(page.getByRole('button', { name: 'Back up now' })).toBeDisabled();
  } else {
    await expect(page.getByText('Backup service', { exact: true })).toBeVisible();
    const restore = table.getByRole('button', { name: 'Restore…' }).first();
    if (await restore.isEnabled()) {
      await restore.click();
      const dialog = page.getByRole('dialog');
      await expect(dialog.getByText('All data of every hotel will be replaced')).toBeVisible();
      // Nothing can be sent before the hotel code is typed.
      const confirm = dialog.getByRole('button', { name: 'Restore this backup' });
      await expect(confirm).toBeDisabled();
      await dialog.getByLabel('Your password').fill('not-sent');
      await dialog.getByLabel(/Type the hotel code/).fill('WRONG');
      await expect(confirm).toBeDisabled();
      await dialog.getByRole('button', { name: 'Cancel' }).click();
    }
  }
  await page.screenshot({ path: `${SHOTS}/${info.project.name}-backups.png`, fullPage: true });
});
