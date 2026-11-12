import { defineConfig, devices } from '@playwright/test';

/**
 * End-to-end tests against a running stack (API + frontend). They need a
 * bootstrapped hotel; credentials come from the environment:
 *   E2E_BASE_URL (default http://localhost:5173), E2E_EMAIL, E2E_PASSWORD
 * The system Chrome is used (channel "chrome") so no browser download is needed.
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
    channel: 'chrome',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'desktop', use: { viewport: { width: 1440, height: 900 } } },
    { name: 'ipad-landscape', use: { ...devices['iPad Pro 11 landscape'], browserName: 'chromium', channel: 'chrome' } },
    { name: 'android-tablet', use: { ...devices['Galaxy Tab S4'], browserName: 'chromium', channel: 'chrome' } },
  ],
});
