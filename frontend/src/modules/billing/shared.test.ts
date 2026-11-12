import { describe, expect, it } from 'vitest';

import { defaultQuantity, toBase } from './shared';

describe('billing helpers', () => {
  it('derives a default quantity from the service pricing unit', () => {
    expect(defaultQuantity('per_item', 3, 2)).toBe(1);
    expect(defaultQuantity('per_stay', 3, 2)).toBe(1);
    expect(defaultQuantity('per_night', 3, 2)).toBe(3);
    expect(defaultQuantity('per_person', 3, 2)).toBe(2);
    expect(defaultQuantity('per_person_night', 3, 2)).toBe(6);
    expect(defaultQuantity('per_night', 0, 2)).toBe(1);
  });

  it('converts a tendered foreign amount to the hotel currency for display', () => {
    expect(toBase(41000, '4100')).toBe(10);
    expect(toBase(100000, '4100')).toBe(24.39);
    expect(toBase(50, '1')).toBe(50);
    expect(toBase(10, null)).toBeNull();
    expect(toBase(Number.NaN, '4100')).toBeNull();
  });
});
