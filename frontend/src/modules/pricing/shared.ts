import { useMemo } from 'react';
import type { TFunction } from 'i18next';
import { useTranslation } from 'react-i18next';

import { useHotelQuery } from '@/api/hooks';
import type { CancellationPolicy, PricingRule, RatePlan, RestrictionIssue } from '@/api/types';
import { useHotel } from '@/auth/AuthProvider';
import { formatDate, formatMoney } from '@/lib/format';
import { pickLocalized } from '@/lib/localized';

export const MEAL_PLANS = ['room_only', 'breakfast', 'half_board', 'full_board', 'all_inclusive'] as const;
export const RULE_KINDS = ['season', 'weekday', 'occupancy', 'long_stay', 'last_minute', 'early_bird'] as const;
export const WEEKDAY_KEYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as const;

export function usePricingLookups() {
  const { i18n } = useTranslation();
  const hotel = useHotel();
  const plans = useHotelQuery<RatePlan[]>('rate_plan', '/rate-plans');
  const policies = useHotelQuery<CancellationPolicy[]>('cancellation_policy', '/cancellation-policies');
  return useMemo(() => {
    const planById = new Map((plans.data ?? []).map((p) => [p.id, p]));
    const policyById = new Map((policies.data ?? []).map((p) => [p.id, p]));
    return {
      plans: plans.data ?? [],
      policies: policies.data ?? [],
      planById,
      policyById,
      defaultPlan: (plans.data ?? []).find((p) => p.is_default),
      planName: (id: string | null | undefined) => {
        const p = id ? planById.get(id) : (plans.data ?? []).find((x) => x.is_default);
        return p ? pickLocalized(p.name, i18n.language, hotel.default_language) || p.code : '';
      },
      policyName: (id: string | null | undefined) => {
        const p = id ? policyById.get(id) : undefined;
        return p ? pickLocalized(p.name, i18n.language, hotel.default_language) || p.code : '';
      },
    };
  }, [plans.data, policies.data, i18n.language, hotel.default_language]);
}

/** "+50 %", "−10 %", "+$20.00", "= $80.00" */
export function adjustmentLabel(mode: string, value: string | number, currency: string, locale: string): string {
  const v = Number(value);
  if (mode === 'percent') return `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v)} %`;
  if (mode === 'set') return `= ${formatMoney(v, currency, locale)}`;
  const money = formatMoney(Math.abs(v), currency, locale);
  return `${v < 0 ? '−' : '+'}${money}`;
}

export function derivationLabel(plan: RatePlan, parentName: string, currency: string, locale: string, t: TFunction): string {
  if (!plan.parent_rate_plan_id || !plan.derive_mode || plan.derive_value === null) return '';
  if (plan.derive_mode === 'amount_per_person') {
    return t('pricing.plans.derived_per_person', { parent: parentName, amount: adjustmentLabel('amount', plan.derive_value, currency, locale) });
  }
  return `${parentName} ${adjustmentLabel(plan.derive_mode, plan.derive_value, currency, locale)}`;
}

export function conditionLabel(rule: PricingRule, t: TFunction): string {
  const c = rule.conditions;
  switch (rule.kind) {
    case 'long_stay':
      return t('pricing.rules.cond_min_nights', { count: c.min_nights ?? 0 });
    case 'last_minute':
      return t('pricing.rules.cond_max_days_before', { count: c.max_days_before ?? 0 });
    case 'early_bird':
      return t('pricing.rules.cond_min_days_before', { count: c.min_days_before ?? 0 });
    case 'occupancy':
      return t('pricing.rules.cond_min_occupancy', { value: c.min_occupancy ?? 0 });
    default:
      return '';
  }
}

export function weekdaysLabel(days: number[], t: TFunction): string {
  if (!days.length || days.length === 7) return t('pricing.rules.every_day');
  return days
    .slice()
    .sort()
    .map((d) => t(`pricing.weekday_short.${WEEKDAY_KEYS[d]}`))
    .join(' ');
}

export function policySummary(p: CancellationPolicy | undefined, t: TFunction): string {
  if (!p) return t('pricing.policies.none');
  if (p.free_until_days === null) return t('pricing.policies.non_refundable_summary');
  return t('pricing.policies.free_until', { count: p.free_until_days });
}

/** Translate a restriction issue returned by the pricing engine. */
export function issueLabel(issue: RestrictionIssue, t: TFunction, locale: string): string {
  const params: Record<string, string> = {};
  for (const [k, v] of Object.entries(issue)) {
    if (k === 'code') continue;
    params[k] = typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v) ? formatDate(v, locale) : String(v ?? '');
  }
  return t(`errors.${issue.code}`, params);
}
