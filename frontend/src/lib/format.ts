/** Locale-aware formatting. Money arrives from the API as decimal strings. */

import { formatInstant, formatRelativeUnit, numberLocale } from '@/lib/intl';

const ZERO_DECIMAL = new Set(['JPY', 'KRW', 'VND', 'CLP', 'PYG', 'ISK', 'UGX', 'XAF', 'XOF', 'XPF', 'KMF', 'GNF', 'RWF', 'DJF', 'BIF', 'VUV']);

export function currencyDecimals(currency: string): number {
  return ZERO_DECIMAL.has(currency) ? 0 : 2;
}

export function formatMoney(amount: string | number | null | undefined, currency: string, locale: string): string {
  if (amount === null || amount === undefined || amount === '') return '—';
  const value = typeof amount === 'number' ? amount : Number(amount);
  const digits = currencyDecimals(currency);
  try {
    return new Intl.NumberFormat(numberLocale(locale), {
      style: 'currency',
      currency,
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    }).format(value);
  } catch {
    return `${value.toFixed(digits)} ${currency}`;
  }
}

export function formatNumber(value: number | string, locale: string, fractionDigits = 0): string {
  return new Intl.NumberFormat(numberLocale(locale), { maximumFractionDigits: fractionDigits }).format(Number(value));
}

/** A file size with the unit that keeps the number short (1 kB = 1000 B). */
export function formatBytes(bytes: number, locale: string): string {
  const units = ['byte', 'kilobyte', 'megabyte', 'gigabyte', 'terabyte'] as const;
  let value = bytes;
  let i = 0;
  while (value >= 1000 && i < units.length - 1) {
    value /= 1000;
    i += 1;
  }
  return new Intl.NumberFormat(numberLocale(locale), { style: 'unit', unit: units[i], unitDisplay: 'short', maximumFractionDigits: i < 2 ? 0 : 1 }).format(value);
}

/** Format an instant in the hotel's time zone (not the device's). */
export function formatDateTime(iso: string | null | undefined, locale: string, timeZone?: string): string {
  if (!iso) return '—';
  return formatInstant(new Date(iso), locale, 'datetime', timeZone);
}

/** Format a calendar date (YYYY-MM-DD) without any time-zone shifting. */
export function formatDate(isoDate: string | null | undefined, locale: string): string {
  if (!isoDate) return '—';
  const [y, m, d] = isoDate.slice(0, 10).split('-').map(Number);
  return formatInstant(new Date(Date.UTC(y, m - 1, d)), locale, 'date', 'UTC');
}

export function formatRelative(iso: string, locale: string, now = Date.now()): string {
  const seconds = Math.round((new Date(iso).getTime() - now) / 1000);
  const abs = Math.abs(seconds);
  if (abs < 60) return formatRelativeUnit(seconds, 'second', locale);
  if (abs < 3600) return formatRelativeUnit(Math.round(seconds / 60), 'minute', locale);
  if (abs < 86400) return formatRelativeUnit(Math.round(seconds / 3600), 'hour', locale);
  return formatRelativeUnit(Math.round(seconds / 86400), 'day', locale);
}

export function countryName(code: string | null | undefined, locale: string): string {
  if (!code) return '—';
  try {
    return new Intl.DisplayNames([numberLocale(locale)], { type: 'region' }).of(code) ?? code;
  } catch {
    return code;
  }
}

export function currencyName(code: string, locale: string): string {
  try {
    return new Intl.DisplayNames([numberLocale(locale)], { type: 'currency' }).of(code) ?? code;
  } catch {
    return code;
  }
}
