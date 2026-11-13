import { defineConfig, devices } from '@playwright/test';

/**
 * End-to-end tests against a running stack (API + frontend). They need a
 * bootstrapped hotel; credentials come from the environment:
 *   E2E_BASE_URL (default http://localhost:5173), E2E_EMAIL, E2E_PASSWORD
 * The system Chrome is used (channel "chrome") so no browser download is needed;
 * the WebKit (Safari) project needs `npx playwright install webkit`.
 */
export default defineConfig({
  testDir: './e2e',
  outputDir: './e2e-results/artifacts',
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:5173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'desktop', use: { viewport: { width: 1440, height: 900 }, channel: 'chrome' } },
    { name: 'ipad-landscape', use: { ...devices['iPad Pro 11 landscape'], browserName: 'chromium', channel: 'chrome' } },
    { name: 'android-tablet', use: { ...devices['Galaxy Tab S4'], browserName: 'chromium', channel: 'chrome' } },
    // Safari's engine (WebKit) with the iPad profile: catches WebKit-only issues
    // (date inputs, flex/grid, Intl, WebSocket) that Chrome emulation does not.
    // Runs in CI (Ubuntu); locally only on request (E2E_WEBKIT=1), since the
    // WebKit build needs Ubuntu's system libraries.
    ...(process.env.CI || process.env.E2E_WEBKIT ? [{ name: 'ipad-safari', use: { ...devices['iPad Pro 11 landscape'] } }] : []),
  ],
});
