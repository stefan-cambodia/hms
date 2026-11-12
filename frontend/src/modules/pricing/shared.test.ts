import i18n, { applyLanguage } from '@/i18n';
import { adjustmentLabel, issueLabel, policySummary, weekdaysLabel } from './shared';

beforeAll(() => applyLanguage('en'));

describe('pricing labels', () => {
  it('formats adjustments with signs and currency', () => {
    expect(adjustmentLabel('percent', '30', 'USD', 'en')).toBe('+30 %');
    expect(adjustmentLabel('percent', '-10.00', 'USD', 'en')).toBe('−10 %');
    expect(adjustmentLabel('amount', '-5', 'USD', 'en')).toBe('−$5.00');
    expect(adjustmentLabel('set', '80', 'USD', 'en')).toBe('= $80.00');
  });
  it('summarises weekdays (Monday = 0)', () => {
    expect(weekdaysLabel([5, 4], i18n.t)).toBe('Fri Sat');
    expect(weekdaysLabel([], i18n.t)).toBe('Every day');
  });
  it('translates restriction issues, formatting dates', () => {
    expect(issueLabel({ code: 'MIN_STAY_NOT_MET', min_stay: 3 }, i18n.t, 'en')).toBe('Minimum stay for this arrival: 3 nights');
    expect(issueLabel({ code: 'STOP_SELL', night: '2026-12-24' }, i18n.t, 'en')).toBe('Closed for sale on Dec 24, 2026');
  });
  it('describes cancellation policies', () => {
    const base = { id: 'p', code: 'X', name: {}, description: {}, penalty_kind: 'nights' as const, penalty_value: '1', no_show_nights: 1, is_active: true, version: 1 };
    expect(policySummary({ ...base, free_until_days: 2 }, i18n.t)).toBe('Free until 2 days before arrival');
    expect(policySummary({ ...base, free_until_days: null }, i18n.t)).toBe('Non-refundable');
  });
});
