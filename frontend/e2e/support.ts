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
    const free = (await get<FreeRoom[]>(s, `/available-rooms?start=${start}&end=${end}`)).filter((r) => (left.get(r.room_type_id) ?? 0) >= spare);
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
