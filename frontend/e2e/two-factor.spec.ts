import { createHmac } from 'node:crypto';

import { expect, type Page, test } from '@playwright/test';

const EMAIL = process.env.E2E_EMAIL ?? 'admin@demo.local';
const PASSWORD = process.env.E2E_PASSWORD ?? 'Demo-Admin-2026';
const SHOTS = 'e2e-results/screenshots';
const STAFF_PASSWORD = 'Night-Shift-2026!';

/** RFC 6238 code of a base32 secret (what the phone's authenticator app shows). */
function totp(secret: string, at = Date.now()): string {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  const bits = [...secret.replace(/\s|=/g, '')].map((c) => alphabet.indexOf(c).toString(2).padStart(5, '0')).join('');
  const key = Buffer.from(bits.match(/.{8}/g)!.map((b) => parseInt(b, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(at / 30_000)));
  const h = createHmac('sha1', key).update(counter).digest();
  const offset = h[h.length - 1] & 15;
  return String((h.readUInt32BE(offset) & 0x7fffffff) % 1_000_000).padStart(6, '0');
}

/** A staff member whose role requires two-factor (created by the administrator through the API). */
async function staffWithRequiredTwoFactor(page: Page): Promise<string> {
  const r = await page.request.post('/api/v1/auth/login', { data: { email: EMAIL, password: PASSWORD } });
  const me = await r.json();
  const base = `/api/v1/hotels/${me.hotels[0].id}`;
  const headers = { 'X-CSRF-Token': me.csrf_token };
  const suffix = `${Date.now() % 1_000_000}`;
  const role = await page.request.post(`${base}/roles`, {
    headers,
    data: { code: `night_${suffix}`, name: `Night audit ${suffix}`, permissions: ['hotel.view', 'reservations.view', 'nightaudit.run'], require_2fa: true },
  });
  expect(role.ok(), await role.text()).toBeTruthy();
  const email = `night.${suffix}@lotus.local`;
  const user = await page.request.post(`${base}/users`, {
    headers,
    data: { email, full_name: `Dara Night ${suffix}`, password: STAFF_PASSWORD, role_ids: [(await role.json()).id], preferred_language: 'en' },
  });
  expect(user.ok(), await user.text()).toBeTruthy();
  await page.request.post('/api/v1/auth/logout', { headers });
  await page.context().clearCookies();
  return email;
}

async function signIn(page: Page, email: string) {
  await page.goto('/');
  await page.evaluate(() => localStorage.setItem('hms.language', 'en'));
  await page.reload();
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill(STAFF_PASSWORD);
  await page.getByRole('button', { name: 'Sign in' }).click();
}

test('a role requiring two-factor: set-up at first sign-in, recovery codes, sign-in with a recovery code', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop', 'workflow checked once; tablets check the set-up screen');
  const email = await staffWithRequiredTwoFactor(page);

  // Password accepted, but nothing else until two-factor is set up.
  await signIn(page, email);
  const gate = page.getByTestId('two-factor-required');
  await expect(gate).toContainText('Set up two-factor authentication');
  await gate.getByRole('button', { name: 'Enable two-factor authentication' }).click();
  await expect(gate.getByTestId('totp-qr')).toBeVisible();
  const secret = (await gate.getByTestId('totp-secret').innerText()).replace(/\s/g, '');
  await page.screenshot({ path: `${SHOTS}/${info.project.name}-two-factor-setup.png`, fullPage: true });

  await gate.locator('input').first().click();
  await page.keyboard.type(totp(secret));
  await gate.getByRole('button', { name: 'Confirm' }).click();
  const dialog = page.getByRole('dialog', { name: 'Your recovery codes' });
  const codes = (await dialog.getByTestId('recovery-codes').innerText()).split(/\s+/).filter(Boolean);
  expect(codes).toHaveLength(10);
  const done = dialog.getByRole('button', { name: 'Done' });
  await expect(done).toBeDisabled(); // codes must be kept first
  await dialog.getByLabel('I have kept these codes somewhere safe').check();
  await done.click();
  await expect(page.getByText('Live', { exact: true })).toBeVisible({ timeout: 15_000 });

  // Lost phone: sign in with a recovery code instead.
  await page.getByRole('button', { name: 'Account menu' }).click();
  await page.getByRole('menuitem', { name: 'Sign out' }).click();
  await signIn(page, email);
  await expect(page.getByText('Enter the 6-digit code', { exact: false })).toBeVisible();
  await page.getByRole('button', { name: 'Lost your phone? Use a recovery code' }).click();
  await page.getByLabel('Recovery code').fill(codes[0]);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page.getByText('Live', { exact: true })).toBeVisible({ timeout: 15_000 });

  // My account counts what is left; the role keeps two-factor on.
  await page.goto('/account');
  await expect(page.getByTestId('recovery-status')).toContainText('9 of 10');
  await expect(page.getByText('Your role requires two-factor authentication')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Disable' })).toHaveCount(0);
  await page.screenshot({ path: `${SHOTS}/${info.project.name}-two-factor-account.png`, fullPage: true });
});

test('the two-factor set-up screen on every device', async ({ page }, info) => {
  const email = await staffWithRequiredTwoFactor(page);
  await signIn(page, email);
  const gate = page.getByTestId('two-factor-required');
  await gate.getByRole('button', { name: 'Enable two-factor authentication' }).click();
  await expect(gate.getByTestId('totp-qr')).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/${info.project.name}-two-factor-gate.png`, fullPage: true });
});
