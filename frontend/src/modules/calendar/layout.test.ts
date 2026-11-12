import { addDays, daysBetween, eachDay, hotelToday, weekday } from '@/lib/dates';
import { barGeometry, dayShift, isMovable, shiftStay, stackLanes } from './layout';

describe('date helpers', () => {
  it('handles month and year boundaries and leap years', () => {
    expect(addDays('2026-12-31', 1)).toBe('2027-01-01');
    expect(addDays('2028-02-28', 1)).toBe('2028-02-29');
    expect(daysBetween('2026-03-28', '2026-04-02')).toBe(5);
    expect(eachDay('2026-01-30', '2026-02-02')).toEqual(['2026-01-30', '2026-01-31', '2026-02-01']);
  });
  it('is not shifted by daylight-saving transitions', () => {
    // Europe switches to summer time on 2026-03-29.
    expect(daysBetween('2026-03-28', '2026-03-30')).toBe(2);
  });
  it('computes weekdays (Monday = 0)', () => {
    expect(weekday('2026-11-16')).toBe(0);
    expect(weekday('2026-11-22')).toBe(6);
  });
  it("uses the hotel's time zone for today", () => {
    const instant = new Date('2026-11-12T20:00:00Z'); // 03:00 next day in Phnom Penh
    expect(hotelToday('Asia/Phnom_Penh', instant)).toBe('2026-11-13');
    expect(hotelToday('America/New_York', instant)).toBe('2026-11-12');
  });
});

describe('barGeometry', () => {
  const W = 40;
  it('draws a stay from mid-arrival to mid-departure', () => {
    expect(barGeometry('2026-11-02', '2026-11-04', '2026-11-01', 7, W, 0)).toEqual({
      left: 60,
      width: 80,
      clippedStart: false,
      clippedEnd: false,
    });
  });
  it('lets a departure and an arrival on the same day share the column without overlap', () => {
    const a = barGeometry('2026-11-01', '2026-11-03', '2026-11-01', 7, W, 0)!;
    const b = barGeometry('2026-11-03', '2026-11-05', '2026-11-01', 7, W, 0)!;
    expect(a.left + a.width).toBeLessThanOrEqual(b.left);
  });
  it('clips stays that start before or end after the visible range', () => {
    const bar = barGeometry('2026-10-25', '2026-11-20', '2026-11-01', 7, W, 0)!;
    expect(bar).toMatchObject({ left: 0, width: 7 * W, clippedStart: true, clippedEnd: true });
  });
  it('hides stays outside the range', () => {
    expect(barGeometry('2026-10-01', '2026-10-05', '2026-11-01', 7, W)).toBeNull();
    expect(barGeometry('2026-11-09', '2026-11-12', '2026-11-01', 7, W)).toBeNull();
  });
});

describe('stackLanes', () => {
  it('reuses a lane once the previous stay has departed', () => {
    const lanes = stackLanes([
      { id: 'a', start: '2026-11-01', end: '2026-11-03' },
      { id: 'b', start: '2026-11-02', end: '2026-11-04' },
      { id: 'c', start: '2026-11-03', end: '2026-11-05' },
    ]);
    expect(Object.fromEntries(lanes.map((l) => [l.item.id, l.lane]))).toEqual({ a: 0, b: 1, c: 0 });
  });
});

describe('drag helpers', () => {
  it('snaps drags to whole days', () => {
    expect(dayShift(55, 40)).toBe(1);
    expect(dayShift(-21, 40)).toBe(-1);
    expect(dayShift(10, 40)).toBe(0);
    expect(shiftStay('2026-11-30', '2026-12-02', 2)).toEqual({ start: '2026-12-02', end: '2026-12-04' });
  });
  it('only lets pending or confirmed stays move', () => {
    expect(isMovable('confirmed')).toBe(true);
    expect(isMovable('confirmed', true)).toBe(false);
    expect(isMovable('checked_in')).toBe(false);
    expect(isMovable('cancelled')).toBe(false);
  });
});
