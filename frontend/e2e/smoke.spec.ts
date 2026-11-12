import { type BrowserContext, expect, type Page, test } from '@playwright/test';

const EMAIL = process.env.E2E_EMAIL ?? 'admin@demo.local';
const PASSWORD = process.env.E2E_PASSWORD ?? 'Demo-Admin-2026';
const SHOTS = 'e2e-results/screenshots';

async function login(page: Page) {
  await page.goto('/');
  await page.evaluate(() => localStorage.setItem('hms.language', 'en'));
  await page.reload();
  await page.getByLabel('Email').fill(EMAIL);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page.getByText('Live')).toBeVisible({ timeout: 15_000 });
}

async function openNav(page: Page) {
  const burger = page.getByRole('button', { name: 'Toggle navigation' });
  if (await burger.isVisible()) await burger.click();
}

test.describe.configure({ mode: 'serial' });

test('sign in, navigate every module, and render on this device', async ({ page }, info) => {
  await login(page);
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  await page.waitForLoadState('networkidle');
  await expect(page.getByText('Rooms in service')).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/${info.project.name}-dashboard.png`, fullPage: true });

  for (const [label, path] of [
    ['Rooms', '/rooms'],
    ['Hotel services', '/services'],
    ['Users & permissions', '/users'],
    ['Configuration', '/settings'],
  ] as const) {
    await openNav(page);
    await page.getByRole('link', { name: label }).click();
    await expect(page).toHaveURL(new RegExp(`${path}`));
    await expect(page.getByRole('heading', { level: 1, name: label })).toBeVisible();
    await page.waitForLoadState('networkidle');
    await page.screenshot({ path: `${SHOTS}/${info.project.name}-${path.slice(1)}.png`, fullPage: true });
  }
});

test('room categories editor and rooms table', async ({ page }, info) => {
  await login(page);
  await page.goto('/settings/room-types');
  await expect(page.getByRole('tab', { name: 'Room categories' })).toHaveAttribute('aria-selected', 'true');
  await page.getByRole('button', { name: 'Add category' }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/${info.project.name}-room-type-drawer.png` });
  await page.keyboard.press('Escape');

  await page.goto('/rooms');
  await expect(page.locator('tbody tr').first()).toBeVisible();
});

test('interface language switches instantly and persists per user', async ({ page }, info) => {
  await login(page);
  for (const [code, label, rooms] of [
    ['km', 'ខ្មែរ', /បន្ទប់/],
    ['zh-CN', '简体中文', /房/],
    ['ru', 'Русский', /Номер/i],
    ['fr', 'Français', /Chambres/],
  ] as const) {
    await page.getByRole('button', { name: /Language|Langue|语言|Язык|ភាសា/ }).click();
    await page.getByRole('menuitem', { name: label }).click();
    await expect(page.locator('html')).toHaveAttribute('lang', code);
    await page.goto('/rooms');
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(rooms);
    await page.waitForLoadState('networkidle');
    await page.screenshot({ path: `${SHOTS}/${info.project.name}-rooms-${code}.png`, fullPage: true });
  }
  // Preference is stored server-side: a fresh session comes back in French.
  await page.context().clearCookies();
  await page.evaluate(() => localStorage.clear());
  await page.goto('/');
  await page.getByLabel('Email').fill(EMAIL);
  await page.getByLabel(/Password|Mot de passe/).fill(PASSWORD);
  await page.getByRole('button', { name: /Sign in|Se connecter/ }).click();
  await expect(page.locator('html')).toHaveAttribute('lang', 'fr');
  // Restore English for the following tests.
  await page.getByRole('button', { name: /Langue|Language/ }).click();
  await page.getByRole('menuitem', { name: 'English' }).click();
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
});

test('a change on one device appears on another without refresh', async ({ browser }, info) => {
  test.skip(info.project.name !== 'desktop', 'one viewport is enough for the sync check');
  const contexts: BrowserContext[] = [await browser.newContext(), await browser.newContext()];
  const [reception, manager] = await Promise.all(contexts.map((c) => c.newPage()));
  await login(reception);
  await login(manager);
  await reception.goto('/settings/structure');
  await manager.goto('/settings/structure');
  const name = `Annex ${Date.now() % 100000}`;
  await expect(reception.getByText(name)).toHaveCount(0);

  await manager.getByRole('button', { name: 'Add building' }).click();
  const dialog = manager.getByRole('dialog');
  await dialog.getByLabel('Code').fill(`AX${Date.now() % 100000}`);
  await dialog.getByLabel('Name').fill(name);
  await dialog.getByRole('button', { name: 'Save' }).click();
  await expect(manager.getByText(name)).toBeVisible();

  // The reception screen updates through the WebSocket, with no reload.
  await expect(reception.getByText(name)).toBeVisible({ timeout: 5_000 });
  await reception.screenshot({ path: `${SHOTS}/realtime-reception.png`, fullPage: true });
  await Promise.all(contexts.map((c) => c.close()));
});

test('offline: banner shown and saving disabled, then recovers', async ({ page, context }, info) => {
  test.skip(info.project.name !== 'desktop', 'one viewport is enough');
  await login(page);
  await page.goto('/settings/profile');
  await expect(page.getByRole('button', { name: 'Save changes' })).toBeVisible();
  await context.setOffline(true);
  // Closing the socket is what the app observes when the server is unreachable.
  await page.evaluate(() => window.dispatchEvent(new Event('offline')));
  await expect(page.getByText('Disconnected from the hotel server')).toBeVisible({ timeout: 40_000 });
  await expect(page.getByRole('button', { name: 'Save changes' })).toBeDisabled();
  await page.screenshot({ path: `${SHOTS}/offline-banner.png` });
  await context.setOffline(false);
  await page.evaluate(() => window.dispatchEvent(new Event('online')));
  await expect(page.getByText('Live')).toBeVisible({ timeout: 40_000 });
  await expect(page.getByText('Disconnected from the hotel server')).toHaveCount(0);
});
