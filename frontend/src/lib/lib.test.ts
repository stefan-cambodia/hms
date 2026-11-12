import { QueryClient } from '@tanstack/react-query';

import { ApiError } from '@/api/client';
import { hotelKey, invalidateForEvent } from '@/api/realtime';
import i18n, { applyLanguage } from '@/i18n';
import { applyFieldErrors, errorMessage, fieldMessage } from '@/lib/errors';
import { formatDate, formatMoney } from '@/lib/format';
import { pickLocalized } from '@/lib/localized';

describe('pickLocalized', () => {
  const text = { en: 'Pool', km: 'អាងហែលទឹក' };
  it('uses the requested language', () => expect(pickLocalized(text, 'km')).toBe('អាងហែលទឹក'));
  it('falls back to the hotel default, then to any translation', () => {
    expect(pickLocalized(text, 'fr', 'en')).toBe('Pool');
    expect(pickLocalized({ ru: 'Бассейн' }, 'fr', 'en')).toBe('Бассейн');
    expect(pickLocalized(null, 'en')).toBe('');
  });
});

describe('formatMoney', () => {
  it('formats decimal strings without float drift', () => {
    expect(formatMoney('0.10', 'USD', 'en')).toBe('$0.10');
    expect(formatMoney('1234.50', 'USD', 'en')).toBe('$1,234.50');
  });
  it('respects zero-decimal currencies and locale separators', () => {
    expect(formatMoney('150000', 'VND', 'en')).toBe('₫150,000');
    expect(formatMoney('1234.5', 'EUR', 'fr').replace(/\s/g, ' ')).toBe('1 234,50 €');
  });
  it('shows a dash for missing values', () => expect(formatMoney(null, 'USD', 'en')).toBe('—'));
});

describe('formatDate', () => {
  it('never shifts calendar dates across time zones', () => {
    expect(formatDate('2026-01-01', 'en')).toBe('Jan 1, 2026');
  });
});

describe('error translation', () => {
  beforeAll(() => applyLanguage('en'));
  it('translates known server codes with parameters', () => {
    const err = new ApiError(429, 'ACCOUNT_LOCKED', 'locked', { retry_after: 30 });
    expect(errorMessage(err)).toBe('Account temporarily locked after failed attempts. Try again in 30 s.');
  });
  it('falls back to a generic message for unknown codes', () => {
    expect(errorMessage(new ApiError(400, 'SOMETHING_NEW', 'x'))).toContain('SOMETHING_NEW');
  });
  it('maps field errors onto form paths', () => {
    const err = new ApiError(409, 'ROOM_NUMBER_EXISTS', 'x', {}, [{ loc: ['body', 'number'], code: 'ROOM_NUMBER_EXISTS' }]);
    const set = vi.fn();
    expect(applyFieldErrors(err, set)).toBe(true);
    expect(set).toHaveBeenCalledWith('number', 'This room number already exists');
  });
  it('translates validation types with context', () => {
    expect(fieldMessage('string_too_short', { min_length: 3 })).toBe('Too short (minimum 3)');
  });
  it('is translated in every language', async () => {
    for (const lng of ['fr', 'zh-CN', 'ru', 'km']) {
      await applyLanguage(lng as 'fr');
      expect(errorMessage(new ApiError(409, 'ROOM_UNAVAILABLE', ''))).not.toBe(i18n.getFixedT('en')('errors.ROOM_UNAVAILABLE'));
    }
    await applyLanguage('en');
  });
});

describe('real-time invalidation', () => {
  it('refreshes dependent lists and the audit log, and nothing in other hotels', async () => {
    const qc = new QueryClient();
    const keys = {
      rooms: hotelKey('h1', 'room', '/rooms', {}),
      types: hotelKey('h1', 'room_type', '/room-types', {}),
      taxes: hotelKey('h1', 'tax_rate', '/tax-rates', {}),
      audit: hotelKey('h1', 'audit', '/audit-logs', {}),
      otherHotel: hotelKey('h2', 'room', '/rooms', {}),
    };
    for (const k of Object.values(keys)) qc.setQueryData(k, []);
    invalidateForEvent(qc, 'h1', 'room');
    const stale = (k: unknown[]) => qc.getQueryState(k)?.isInvalidated;
    expect(stale(keys.rooms)).toBe(true);
    expect(stale(keys.types)).toBe(true); // room counts per category change
    expect(stale(keys.audit)).toBe(true);
    expect(stale(keys.taxes)).toBe(false);
    expect(stale(keys.otherHotel)).toBe(false);
  });
});

describe('hotel-local date-times', () => {
  it('converts between hotel time and UTC instants', async () => {
    const { hotelLocalToIso, isoToHotelLocal, tzOffsetMinutes } = await import('./dates');
    expect(tzOffsetMinutes(new Date('2026-11-12T00:00:00Z'), 'Asia/Phnom_Penh')).toBe(420);
    expect(hotelLocalToIso('2026-11-12 09:00:00', 'Asia/Phnom_Penh')).toBe('2026-11-12T02:00:00.000Z');
    expect(hotelLocalToIso('2026-11-12 09:00', 'Europe/Paris')).toBe('2026-11-12T08:00:00.000Z');
    expect(hotelLocalToIso('2026-07-01 09:00', 'Europe/Paris')).toBe('2026-07-01T07:00:00.000Z');
    expect(isoToHotelLocal('2026-11-12T02:00:00Z', 'Asia/Phnom_Penh')).toBe('2026-11-12 09:00:00');
  });
});
