/** Pure layout logic for the reservation timeline (unit-tested). */
import { addDays, daysBetween } from '@/lib/dates';

export interface Bar {
  left: number;
  width: number;
  /** The item starts before the visible range. */
  clippedStart: boolean;
  /** The item ends after the visible range. */
  clippedEnd: boolean;
}

/**
 * A stay from `start` to `end` (departure day) is drawn from the middle of the
 * arrival column to the middle of the departure column, the usual PMS
 * convention: a departure and an arrival on the same day share that column
 * without overlapping. Returns null when the item is not visible.
 */
export function barGeometry(start: string, end: string, rangeStart: string, days: number, colWidth: number, gap = 2): Bar | null {
  const from = daysBetween(rangeStart, start) + 0.5;
  const to = daysBetween(rangeStart, end) + 0.5;
  const maxX = days * colWidth;
  const left = Math.max(0, from * colWidth);
  const right = Math.min(maxX, to * colWidth);
  if (right <= 0 || left >= maxX || right - left <= 0) return null;
  return {
    left: left + gap / 2,
    width: Math.max(4, right - left - gap),
    clippedStart: from < 0,
    clippedEnd: to * colWidth > maxX,
  };
}

/**
 * Assign each item to the first lane where it does not overlap a previous
 * item (half-open [start, end)). Used to stack unassigned bookings.
 */
export function stackLanes<T extends { start: string; end: string }>(items: T[]): { item: T; lane: number }[] {
  const sorted = [...items].sort((a, b) => (a.start === b.start ? a.end.localeCompare(b.end) : a.start.localeCompare(b.start)));
  const laneEnds: string[] = [];
  return sorted.map((item) => {
    let lane = laneEnds.findIndex((end) => end <= item.start);
    if (lane === -1) {
      lane = laneEnds.length;
      laneEnds.push(item.end);
    } else {
      laneEnds[lane] = item.end;
    }
    return { item, lane };
  });
}

/** Whole-day shift for a horizontal drag distance. */
export function dayShift(deltaX: number, colWidth: number): number {
  return Math.round(deltaX / colWidth);
}

export function shiftStay(start: string, end: string, days: number): { start: string; end: string } {
  return { start: addDays(start, days), end: addDays(end, days) };
}

export const STATUS_COLORS: Record<string, string> = {
  pending: 'brass',
  confirmed: 'lagoon',
  checked_in: 'green',
  checked_out: 'gray',
  cancelled: 'red',
  no_show: 'red',
};

/** Statuses that can still be moved on the calendar. */
export function isMovable(status: string | null, checkedIn = false): boolean {
  return (status === 'pending' || status === 'confirmed') && !checkedIn;
}

export const RANGE_PRESETS = [7, 14, 31] as const;
