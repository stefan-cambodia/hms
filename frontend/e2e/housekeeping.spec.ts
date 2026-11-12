import { expect, type Page, test } from '@playwright/test';

const EMAIL = process.env.E2E_EMAIL ?? 'admin@demo.local';
const PASSWORD = process.env.E2E_PASSWORD ?? 'Demo-Admin-2026';
const SHOTS = 'e2e-results/screenshots';

interface Session {
  csrf: string;
  hotel: { id: string; timezone: string };
}

async function apiLogin(page: Page): Promise<Session> {
  const r = await page.request.post('/api/v1/auth/login', { data: { email: EMAIL, password: PASSWORD } });
  expect(r.ok()).toBeTruthy();
  const me = await r.json();
  return { csrf: me.csrf_token, hotel: me.hotels[0] };
}

async function get<T>(page: Page, s: Session, path: string): Promise<T> {
  const r = await page.request.get(`/api/v1/hotels/${s.hotel.id}${path}`);
  expect(r.ok(), `${path}: ${r.status()}`).toBeTruthy();
  return (await r.json()) as T;
}

function hotelDay(tz: string, offset = 0): string {
  const today = new Intl.DateTimeFormat('en-CA', { timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
  const d = new Date(`${today}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + offset);
  return d.toISOString().slice(0, 10);
}

/** A room free tonight in a category that is not sold out (demo data is shared between runs). */
async function freeRoomTonight(page: Page, s: Session): Promise<string> {
  const start = hotelDay(s.hotel.timezone);
  const end = hotelDay(s.hotel.timezone, 1);
  const availability = await get<{ room_type_id: string; nights: { available: number }[] }[]>(page, s, `/availability?start=${start}&end=${end}`);
  const left = new Map(availability.map((a) => [a.room_type_id, Math.min(...a.nights.map((n) => n.available))]));
  const free = (await get<{ number: string; room_type_id: string }[]>(page, s, `/available-rooms?start=${start}&end=${end}`)).filter(
    (r) => (left.get(r.room_type_id) ?? 0) > 1,
  );
  expect(free.length, 'a free room tonight').toBeGreaterThan(0);
  return free[Math.floor(Math.random() * free.length)].number;
}

async function openApp(page: Page, path: string) {
  await page.goto('/');
  await page.evaluate(() => localStorage.setItem('hms.language', 'en'));
  await page.goto(path);
  await expect(page.getByText('Live')).toBeVisible({ timeout: 15_000 });
}

async function pickRoom(page: Page, dialog: ReturnType<Page['getByRole']>, number: string) {
  await dialog.getByRole('textbox', { name: 'Room', exact: true }).click();
  await dialog.getByRole('textbox', { name: 'Room', exact: true }).fill(number);
  await page.getByRole('option', { name: new RegExp(`^${number} ·`) }).click();
}

test.describe.configure({ mode: 'serial' });

test('cleaning task: add, start, done, approve; the room shows as inspected', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop', 'workflow checked once; tablets check the screens');
  const s = await apiLogin(page);
  const tasks = await get<{ room_number: string; task_type: string }[]>(page, s, '/housekeeping/tasks');
  const rooms = await get<{ number: string; is_active: boolean }[]>(page, s, '/rooms');
  const busy = new Set(tasks.filter((t) => t.task_type === 'deep_clean').map((t) => t.room_number));
  const room = rooms.find((r) => r.is_active && !busy.has(r.number));
  test.skip(!room, 'every room already had a deep clean today');

  await openApp(page, '/housekeeping');
  await page.getByRole('button', { name: 'Add task' }).click();
  const dialog = page.getByRole('dialog');
  await pickRoom(page, dialog, room!.number);
  await dialog.getByRole('textbox', { name: 'Task' }).click();
  await page.getByRole('option', { name: 'Deep clean' }).click();
  await dialog.getByRole('button', { name: 'Add task' }).click();
  await expect(page.getByText('Task added')).toBeVisible();

  await page.locator('label', { hasText: /^All$/ }).click();
  const row = page.locator(`[data-task="${room!.number}-deep_clean"]`);
  await expect(row).toBeVisible();
  await row.getByRole('button', { name: 'Start' }).click();
  await expect(row).toContainText('In progress');
  await row.getByRole('button', { name: 'Done' }).click();
  await expect(row.getByRole('button', { name: 'Approve' })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/${info.project.name}-housekeeping-tasks.png`, fullPage: true });
  await row.getByRole('button', { name: 'Approve' }).click();
  await expect(row).toContainText('Inspected by');

  await page.getByRole('tab', { name: 'Rooms' }).click();
  await expect(page.locator(`[data-room-tile="${room!.number}"]`)).toContainText('Inspected');
});

test('maintenance: report with room out of service, work, complete; room back in service and to clean', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop', 'workflow checked once');
  const s = await apiLogin(page);
  const number = await freeRoomTonight(page, s);
  const title = `Leaking tap ${Date.now() % 100000}`;

  await openApp(page, '/maintenance');
  await page.getByRole('button', { name: 'Report a problem' }).click();
  const dialog = page.getByRole('dialog');
  await pickRoom(page, dialog, number);
  await dialog.getByRole('textbox', { name: 'Type of problem' }).click();
  await page.getByRole('option', { name: 'Plumbing' }).click();
  await dialog.getByRole('textbox', { name: /^Problem/ }).fill(title);
  await dialog.getByLabel('Take the room out of service').check();
  await dialog.getByRole('button', { name: 'Send report' }).click();
  await expect(page.getByText(/Request MT-\d+ recorded/)).toBeVisible();

  const detail = page.getByTestId('maintenance-detail');
  await expect(detail).toContainText(title);
  await expect(detail).toContainText('Out of service from');
  await detail.getByRole('button', { name: 'Start work' }).click();
  await expect(detail).toContainText('In progress');
  await page.screenshot({ path: `${SHOTS}/${info.project.name}-maintenance.png`, fullPage: true });
  await detail.getByRole('button', { name: 'Complete' }).click();
  const close = page.getByRole('dialog', { name: 'Complete' });
  await close.getByLabel('Work done').fill('Washer replaced');
  await close.getByRole('button', { name: 'Complete' }).click();
  await expect(page.getByText('Request completed')).toBeVisible();
  await expect(detail).toContainText('Washer replaced');
  await expect(detail).toContainText('The room is in service.');

  // The room is sellable again and waits for housekeeping.
  await page.goto('/front-desk?tab=rooms');
  const tile = page.locator(`[data-room-tile="${number}"]`);
  await expect(tile).toContainText('Dirty');
  await expect(tile).toContainText('Touch-up');
});

test('housekeeping and maintenance screens on every device', async ({ page }, info) => {
  await apiLogin(page);
  await openApp(page, '/housekeeping?tab=mine');
  await expect(page.getByRole('tab', { name: 'My tasks' })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/${info.project.name}-housekeeping-mine.png`, fullPage: true });
  await page.goto('/maintenance');
  await expect(page.getByRole('button', { name: 'Report a problem' })).toBeVisible();
  await page.waitForLoadState('networkidle');
  await page.screenshot({ path: `${SHOTS}/${info.project.name}-maintenance-list.png`, fullPage: true });
});
