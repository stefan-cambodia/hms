import { expect, type Page, test } from '@playwright/test';

const EMAIL = process.env.E2E_EMAIL ?? 'admin@demo.local';
const PASSWORD = process.env.E2E_PASSWORD ?? 'Demo-Admin-2026';
const SHOTS = 'e2e-results/screenshots';
const LOGO = 'e2e/fixtures/logo.png';
const PHOTO = 'e2e/fixtures/room.jpg'; // carries camera EXIF and a GPS position

interface Session {
  csrf: string;
  hotel: { id: string };
}

async function login(page: Page): Promise<Session> {
  const r = await page.request.post('/api/v1/auth/login', { data: { email: EMAIL, password: PASSWORD } });
  expect(r.ok()).toBeTruthy();
  const me = await r.json();
  await page.goto('/');
  await page.evaluate(() => localStorage.setItem('hms.language', 'en'));
  return { csrf: me.csrf_token, hotel: me.hotels[0] };
}

/** A category of its own, so repeated runs never reach the photo limit. */
async function photoCategory(page: Page, s: Session): Promise<{ id: string; code: string }> {
  const code = `PH${Date.now() % 100000}`;
  const r = await page.request.post(`/api/v1/hotels/${s.hotel.id}/room-types`, {
    data: { code, name: { en: 'Garden suite' }, base_occupancy: 2, max_occupancy: 2, max_adults: 2, max_children: 0, base_price: '120' },
    headers: { 'X-CSRF-Token': s.csrf },
  });
  expect(r.ok(), await r.text()).toBeTruthy();
  return { id: (await r.json()).id, code };
}

test.describe.configure({ mode: 'serial' });

test('logo: upload in the hotel profile, shown in the header, then removed', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop', 'workflow checked once; tablets check the screens');
  await login(page);
  await page.goto('/settings/profile');
  const card = page.getByTestId('logo-card');
  await expect(card).toBeVisible({ timeout: 15_000 });

  await card.locator('input[type="file"]').setInputFiles(LOGO);
  await expect(page.getByText('Logo saved')).toBeVisible();
  await expect(card.getByRole('img', { name: 'Logo' })).toBeVisible();
  const header = page.getByTestId('header-logo');
  await expect(header).toBeVisible();
  // Served as a re-encoded PNG (transparency kept), never as the uploaded bytes.
  const served = await page.request.get((await header.getAttribute('src'))!);
  expect(served.headers()['content-type']).toBe('image/png');
  expect(served.headers()['x-content-type-options']).toBe('nosniff');
  await page.screenshot({ path: `${SHOTS}/${info.project.name}-logo.png` });

  await card.getByRole('button', { name: 'Remove the logo' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Remove the logo' }).click();
  await expect(page.getByText('Logo removed')).toBeVisible();
  await expect(header).toHaveCount(0);
  await expect(card).toContainText('No logo');
});

test('room category photos: add, reorder, view, delete; location data removed', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop', 'workflow checked once; tablets check the screens');
  const s = await login(page);
  const category = await photoCategory(page, s);
  await page.goto('/settings/room-types');
  await page.locator('tr', { hasText: category.code }).getByRole('button', { name: 'Edit' }).click();
  const gallery = page.getByRole('dialog').getByTestId('media-room_type');
  await expect(gallery).toContainText('No photos yet.');

  await gallery.locator('input[type="file"]').setInputFiles([PHOTO, LOGO]);
  await expect(page.getByText('Photos added')).toBeVisible();
  const tiles = gallery.locator('[data-media-id]');
  await expect(tiles).toHaveCount(2);
  await expect(gallery).toContainText('2 of 20');
  const photoId = (await tiles.nth(0).getAttribute('data-media-id'))!;

  // The stored photo has no EXIF block left (camera, GPS position).
  const full = await page.request.get(`/api/v1/hotels/${s.hotel.id}/media/${photoId}/content`);
  expect(full.headers()['content-type']).toBe('image/jpeg');
  expect((await full.body()).includes(Buffer.from('Exif\0\0'))).toBe(false);

  await tiles.nth(1).getByRole('button', { name: 'Move left' }).click();
  await expect(tiles.nth(1)).toHaveAttribute('data-media-id', photoId);
  await page.screenshot({ path: `${SHOTS}/${info.project.name}-room-type-photos.png` });

  await tiles.nth(1).getByRole('button', { name: /^View / }).click();
  const viewer = page.getByRole('dialog', { name: 'room.jpg' });
  await expect(viewer.getByRole('img', { name: 'room.jpg' })).toBeVisible();
  await expect(viewer).toContainText('2 / 2');
  await viewer.getByRole('button', { name: 'Delete' }).click();
  await page.getByRole('dialog', { name: 'Delete this photo?' }).getByRole('button', { name: 'Delete' }).click();
  await expect(tiles).toHaveCount(1);
  await expect(gallery).toContainText('1 of 20');

  const r = await page.request.delete(`/api/v1/hotels/${s.hotel.id}/room-types/${category.id}`, { headers: { 'X-CSRF-Token': s.csrf } });
  expect(r.status()).toBe(204);
});

test('maintenance: report a problem with a photo taken on the spot', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop', 'workflow checked once; tablets check the screens');
  await login(page);
  await page.goto('/maintenance');
  await expect(page.getByText('Live')).toBeVisible({ timeout: 15_000 });
  await page.getByRole('button', { name: 'Report a problem' }).click();
  const dialog = page.getByRole('dialog', { name: 'Report a problem' });
  await dialog.getByText('Elsewhere', { exact: true }).click();
  await dialog.getByRole('textbox', { name: 'Location' }).fill('Pool deck');
  await dialog.getByRole('textbox', { name: /^Problem/ }).fill(`Broken tile ${Date.now() % 100000}`);
  await dialog.locator('input[type="file"]').setInputFiles(PHOTO);
  await expect(dialog.getByTestId('photo-preview')).toHaveCount(1);
  await dialog.getByRole('button', { name: 'Send report' }).click();
  await expect(page.getByText(/Request MT-\d+ recorded/)).toBeVisible();

  const detail = page.getByTestId('maintenance-detail');
  const photos = detail.getByTestId('media-maintenance_request');
  await expect(photos.locator('[data-media-id]')).toHaveCount(1);
  await expect(photos).toContainText('1 of 10');
  await page.screenshot({ path: `${SHOTS}/${info.project.name}-maintenance-photo.png`, fullPage: true });
});

test('logo card and photo galleries on every device', async ({ page }, info) => {
  await login(page);
  await page.goto('/settings/profile');
  await expect(page.getByTestId('logo-card')).toBeVisible({ timeout: 15_000 });
  await page.goto('/settings/room-types');
  await page.locator('tbody tr').first().getByRole('button', { name: 'Edit' }).click();
  const gallery = page.getByRole('dialog').getByTestId('media-room_type');
  await expect(gallery.getByRole('button', { name: 'Add photos' })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/${info.project.name}-room-type-gallery.png` });
});
