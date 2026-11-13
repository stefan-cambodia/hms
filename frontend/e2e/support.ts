import { type APIRequestContext, expect } from '@playwright/test';

export interface RoomContext {
  request: APIRequestContext;
  csrf: string;
  hotel: { id: string; timezone: string };
}

export interface FreeRoom {
  id: string;
  number: string;
  room_type_id: string;
}

/** The hotel's calendar day, `offset` days from today. */
export function hotelDay(tz: string, offset = 0): string {
  const today = new Intl.DateTimeFormat('en-CA', { timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
  const d = new Date(`${today}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + offset);
  return d.toISOString().slice(0, 10);
}

async function get<T>(s: RoomContext, path: string): Promise<T> {
  const r = await s.request.get(`/api/v1/hotels/${s.hotel.id}${path}`);
  expect(r.ok(), `GET ${path}: ${r.status()}`).toBeTruthy();
  return (await r.json()) as T;
}

/**
 * A room that is free from today for `nights` nights, in a category with at least
 * `spare` rooms still unsold (so the test's own booking cannot be refused).
 *
 * The end-to-end tests share the demo hotel, and every run leaves guests in
 * house. When tonight is sold out, the helper adds a room to the category with
 * the most rooms (named "T-…", through the normal room API) instead of failing:
 * the tests check the screens, not the demo hotel's occupancy.
 */
export async function freeRoom(s: RoomContext, nights = 1, spare = 1): Promise<FreeRoom> {
  const start = hotelDay(s.hotel.timezone);
  const end = hotelDay(s.hotel.timezone, nights);
  const pick = async () => {
    const availability = await get<{ room_type_id: string; nights: { available: number }[] }[]>(s, `/availability?start=${start}&end=${end}`);
    const left = new Map(availability.map((a) => [a.room_type_id, Math.min(...a.nights.map((n) => n.available))]));
    // A room free tonight can still hold a guest who has not checked out yet
    // (an overdue departure left by an earlier run): check-in would be refused.
    const occupied = new Set(
      (await get<{ room_id: string; occupant: unknown }[]>(s, '/room-board')).filter((r) => r.occupant).map((r) => r.room_id),
    );
    const free = (await get<FreeRoom[]>(s, `/available-rooms?start=${start}&end=${end}`)).filter(
      (r) => (left.get(r.room_type_id) ?? 0) >= spare && !occupied.has(r.id),
    );
    return { availability, free };
  };
  let { availability, free } = await pick();
  if (free.length === 0) {
    const rooms = await get<{ room_type_id: string }[]>(s, '/rooms');
    const count = new Map<string, number>();
    for (const r of rooms) count.set(r.room_type_id, (count.get(r.room_type_id) ?? 0) + 1);
    const typeId = [...availability.map((a) => a.room_type_id)].sort((a, b) => (count.get(b) ?? 0) - (count.get(a) ?? 0))[0];
    for (let i = 0; i < spare; i++) {
      const number = `T-${Date.now().toString(36).toUpperCase()}${i}`;
      const r = await s.request.post(`/api/v1/hotels/${s.hotel.id}/rooms`, { data: { room_type_id: typeId, number }, headers: { 'X-CSRF-Token': s.csrf } });
      expect(r.ok(), `create room ${number}: ${await r.text()}`).toBeTruthy();
    }
    ({ free } = await pick());
  }
  expect(free.length, 'a free room tonight').toBeGreaterThan(0);
  const room = free[Math.floor(Math.random() * free.length)];
  const r = await s.request.post(`/api/v1/hotels/${s.hotel.id}/rooms/${room.id}/housekeeping-status`, {
    data: { status: 'clean' },
    headers: { 'X-CSRF-Token': s.csrf },
  });
  expect(r.ok(), `clean room ${room.number}: ${await r.text()}`).toBeTruthy();
  return room;
}

/**
 * Make sure the calendar's first days show at least one stay and one room
 * block (a fresh installation has neither). Created through the API.
 */
export async function calendarSample(s: RoomContext): Promise<void> {
  const start = hotelDay(s.hotel.timezone, 1);
  const end = hotelDay(s.hotel.timezone, 3);
  const post = async (path: string, data: unknown) => {
    const r = await s.request.post(`/api/v1/hotels/${s.hotel.id}${path}`, { data, headers: { 'X-CSRF-Token': s.csrf } });
    expect(r.ok(), `POST ${path}: ${await r.text()}`).toBeTruthy();
  };
  const blocks = await get<unknown[]>(s, `/room-blocks?start=${start}&end=${end}`);
  if (blocks.length === 0) {
    const [room] = await get<FreeRoom[]>(s, `/available-rooms?start=${start}&end=${end}`);
    await post('/room-blocks', { room_id: room.id, start_date: start, end_date: end, reason: 'maintenance', notes: 'E2E sample' });
  }
  const free = await get<FreeRoom[]>(s, `/available-rooms?start=${start}&end=${end}`);
  await post('/reservations', {
    arrival: start,
    departure: end,
    guest: { first_name: 'Calendar', last_name: 'Sample' },
    rooms: [{ room_type_id: free[0].room_type_id, room_id: free[0].id, adults: 1 }],
    override_restrictions: true,
  });
}
