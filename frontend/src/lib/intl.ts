/**
 * Intl with a fallback for languages the browser has no data for.
 *
 * Desktop Chrome ships without Khmer formatting data: `Intl.*('km')` then
 * silently uses the device's own language, so a Khmer screen showed French
 * or English dates. When the data is missing, dates are written with the
 * Khmer month and weekday names below, and numbers and names use US English
 * (dot decimal, "$"), never whatever language the device happens to have.
 * Safari (iPad) has the data and formats natively.
 */

const support = new Map<string, boolean>();

export function hasIntlData(locale: string): boolean {
  let ok = support.get(locale);
  if (ok === undefined) {
    try {
      ok = Intl.DateTimeFormat.supportedLocalesOf([locale]).length > 0 && Intl.NumberFormat.supportedLocalesOf([locale]).length > 0;
    } catch {
      ok = false;
    }
    support.set(locale, ok);
  }
  return ok;
}

/** Locale for numbers, currencies and display names. */
export function numberLocale(locale: string): string {
  return hasIntlData(locale) ? locale : 'en-US';
}

export const KM_MONTHS = ['មករា', 'កុម្ភៈ', 'មីនា', 'មេសា', 'ឧសភា', 'មិថុនា', 'កក្កដា', 'សីហា', 'កញ្ញា', 'តុលា', 'វិច្ឆិកា', 'ធ្នូ'];
// Sunday first, like Date.getDay().
export const KM_WEEKDAYS = ['អាទិត្យ', 'ច័ន្ទ', 'អង្គារ', 'ពុធ', 'ព្រហស្បតិ៍', 'សុក្រ', 'សៅរ៍'];
export const KM_WEEKDAYS_SHORT = ['អា', 'ច', 'អ', 'ពុ', 'ព្រ', 'សុ', 'ស'];

export type DateShape = 'date' | 'datetime' | 'day_month' | 'weekday_long_date' | 'weekday_short' | 'month_short';

const OPTIONS: Record<DateShape, Intl.DateTimeFormatOptions> = {
  date: { dateStyle: 'medium' },
  datetime: { dateStyle: 'medium', timeStyle: 'short' },
  day_month: { day: 'numeric', month: 'short' },
  weekday_long_date: { weekday: 'short', day: 'numeric', month: 'long', year: 'numeric' },
  weekday_short: { weekday: 'short' },
  month_short: { month: 'short' },
};

const WEEKDAYS_EN = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

function wallClock(date: Date, timeZone?: string) {
  const p: Record<string, string> = {};
  for (const part of new Intl.DateTimeFormat('en-US', {
    timeZone,
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
    weekday: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(date)) {
    p[part.type] = part.value;
  }
  return { year: p.year, month: Number(p.month) - 1, day: p.day, weekday: WEEKDAYS_EN.indexOf(p.weekday), time: `${p.hour}:${p.minute}` };
}

/** Khmer date text, independent of the browser's locale data. */
export function khmerDate(date: Date, shape: DateShape, timeZone?: string): string {
  const c = wallClock(date, timeZone);
  const month = KM_MONTHS[c.month];
  switch (shape) {
    case 'date':
      return `${c.day} ${month} ${c.year}`;
    case 'datetime':
      return `${c.day} ${month} ${c.year} ម៉ោង ${c.time}`;
    case 'day_month':
      return `${c.day} ${month}`;
    case 'weekday_long_date':
      return `ថ្ងៃ${KM_WEEKDAYS[c.weekday]} ${c.day} ${month} ${c.year}`;
    case 'weekday_short':
      return KM_WEEKDAYS_SHORT[c.weekday];
    case 'month_short':
      return month;
  }
}

export function formatInstant(date: Date, locale: string, shape: DateShape, timeZone?: string): string {
  if (hasIntlData(locale)) return new Intl.DateTimeFormat(locale, { ...OPTIONS[shape], timeZone }).format(date);
  if (locale.startsWith('km')) return khmerDate(date, shape, timeZone);
  return new Intl.DateTimeFormat('en-US', { ...OPTIONS[shape], timeZone }).format(date);
}

const KM_UNITS = { second: 'វិនាទី', minute: 'នាទី', hour: 'ម៉ោង', day: 'ថ្ងៃ' } as const;

export function formatRelativeUnit(value: number, unit: keyof typeof KM_UNITS, locale: string): string {
  if (hasIntlData(locale)) return new Intl.RelativeTimeFormat(locale, { numeric: 'auto' }).format(value, unit);
  if (!locale.startsWith('km')) return new Intl.RelativeTimeFormat('en-US', { numeric: 'auto' }).format(value, unit);
  if (value === 0) return 'ឥឡូវនេះ';
  const n = Math.abs(value);
  return value < 0 ? `${n} ${KM_UNITS[unit]}មុន` : `ក្នុងរយៈពេល ${n} ${KM_UNITS[unit]}`;
}
