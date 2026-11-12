/**
 * Calendar-date helpers. Stay dates are plain YYYY-MM-DD strings in the
 * hotel's calendar: they are never converted through the device's time zone.
 */

const DAY = 86_400_000;

function toUtc(iso: string): number {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
  return Date.UTC(y, m - 1, d);
}

function fromUtc(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10);
}

export function addDays(iso: string, days: number): string {
  return fromUtc(toUtc(iso) + days * DAY);
}

/** Whole days from `a` to `b` (b - a). */
export function daysBetween(a: string, b: string): number {
  return Math.round((toUtc(b) - toUtc(a)) / DAY);
}

/** Every date in [start, end). */
export function eachDay(start: string, end: string): string[] {
  const n = Math.max(0, daysBetween(start, end));
  return Array.from({ length: n }, (_, i) => addDays(start, i));
}

/** 0 = Monday … 6 = Sunday. */
export function weekday(iso: string): number {
  return (new Date(toUtc(iso)).getUTCDay() + 6) % 7;
}

/** Today's date in the hotel's time zone (not the device's). */
export function hotelToday(timeZone: string, now: Date = new Date()): string {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(now);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? '';
  return `${get('year')}-${get('month')}-${get('day')}`;
}

export function minDate(a: string, b: string): string {
  return a < b ? a : b;
}

export function maxDate(a: string, b: string): string {
  return a > b ? a : b;
}

/** Short day label in the user's language, e.g. "Mo 12" / "一 12" / "ច 12". */
export function dayLabel(iso: string, locale: string): { weekday: string; day: string; month: string } {
  const date = new Date(toUtc(iso));
  return {
    weekday: new Intl.DateTimeFormat(locale, { weekday: 'short', timeZone: 'UTC' }).format(date),
    day: String(date.getUTCDate()),
    month: new Intl.DateTimeFormat(locale, { month: 'short', timeZone: 'UTC' }).format(date),
  };
}
