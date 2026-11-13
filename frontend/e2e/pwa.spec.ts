import { expect, test } from '@playwright/test';

// Installable on Android (manifest, PNG and maskable icons) and on iPad
// ("Add to Home Screen": apple-touch-icon, standalone mode).
test('the app is installable on tablets', async ({ page, request }, info) => {
  test.skip(info.project.name !== 'desktop', 'static files: checked once');
  const manifest = await (await request.get('/manifest.webmanifest')).json();
  expect(manifest).toMatchObject({ id: '/', start_url: '/', display: 'standalone', short_name: 'HMS' });
  const sizes = manifest.icons.map((i: { sizes: string; purpose: string }) => `${i.sizes}/${i.purpose}`);
  expect(sizes).toEqual(expect.arrayContaining(['192x192/any', '512x512/any', '512x512/maskable']));
  for (const icon of manifest.icons) {
    const r = await request.get(icon.src);
    expect(r.ok(), icon.src).toBeTruthy();
    expect(r.headers()['content-type']).toContain(icon.type);
  }
  await page.goto('/');
  const touch = await page.locator('link[rel="apple-touch-icon"]').getAttribute('href');
  expect((await request.get(touch as string)).headers()['content-type']).toContain('image/png');
  await expect(page.locator('meta[name="apple-mobile-web-app-capable"]')).toHaveAttribute('content', 'yes');
});
