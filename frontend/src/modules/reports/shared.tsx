import { Card, Group, Text } from '@mantine/core';
import { IconArrowDownRight, IconArrowUpRight, IconMinus } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { addDays } from '@/lib/dates';
import { formatMoney, formatNumber } from '@/lib/format';

export type Preset = 'this_month' | 'last_month' | 'last_30' | 'this_year' | 'custom';
export type Compare = 'none' | 'previous' | 'last_year';

/** [start, end) for a preset, from the hotel's today (YYYY-MM-DD). */
export function presetRange(preset: Exclude<Preset, 'custom'>, today: string): [string, string] {
  const [y, m] = today.split('-').map(Number);
  const first = (yy: number, mm: number) => `${yy}-${String(mm).padStart(2, '0')}-01`;
  const next = (yy: number, mm: number): [number, number] => (mm === 12 ? [yy + 1, 1] : [yy, mm + 1]);
  switch (preset) {
    case 'this_month':
      return [first(y, m), first(...next(y, m))];
    case 'last_month': {
      const [py, pm] = m === 1 ? [y - 1, 12] : [y, m - 1];
      return [first(py, pm), first(y, m)];
    }
    case 'last_30':
      return [addDays(today, -30), today];
    case 'this_year':
      return [`${y}-01-01`, `${y + 1}-01-01`];
  }
}

export function useFormatters(currency: string) {
  const { i18n } = useTranslation();
  const lang = i18n.language;
  return {
    lang,
    money: (v: string | number | null | undefined) => (v === null || v === undefined ? '—' : formatMoney(v, currency, lang)),
    pct: (v: string | number | null | undefined) => (v === null || v === undefined ? '—' : `${formatNumber(v, lang, 1)} %`),
    num: (v: string | number | null | undefined, digits = 0) => (v === null || v === undefined ? '—' : formatNumber(v, lang, digits)),
    shortDate: (iso: string) => new Intl.DateTimeFormat(lang, { day: 'numeric', month: 'short', timeZone: 'UTC' }).format(new Date(`${iso}T00:00:00Z`)),
    longDate: (iso: string) =>
      new Intl.DateTimeFormat(lang, { weekday: 'short', day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' }).format(new Date(`${iso}T00:00:00Z`)),
  };
}

export interface Delta {
  /** Display text, e.g. "+3.2 pts" or "−12 %". */
  text: string;
  direction: 'up' | 'down' | 'flat';
  good: boolean | null;
}

/** Difference with the comparison period: points for percentages, relative % otherwise. */
export function delta(
  current: string | number | null,
  previous: string | number | null,
  kind: 'points' | 'relative',
  lang: string,
  higherIsBetter = true,
): Delta | null {
  if (current === null || previous === null) return null;
  const c = Number(current);
  const p = Number(previous);
  let value: number;
  if (kind === 'points') value = c - p;
  else {
    if (p === 0) return null;
    value = ((c - p) / Math.abs(p)) * 100;
  }
  const rounded = Math.round(value * 10) / 10;
  const direction = rounded > 0 ? 'up' : rounded < 0 ? 'down' : 'flat';
  const sign = rounded > 0 ? '+' : rounded < 0 ? '−' : '±';
  const body = formatNumber(Math.abs(rounded), lang, 1);
  return {
    text: kind === 'points' ? `${sign}${body} pts` : `${sign}${body} %`,
    direction,
    good: direction === 'flat' ? null : (direction === 'up') === higherIsBetter,
  };
}

/** Stat tile: label, value, optional delta versus a named period. */
export function StatTile({ label, value, sub, change, vsLabel, testId }: { label: string; value: string; sub?: string; change?: Delta | null; vsLabel?: string; testId?: string }) {
  const Icon = !change ? null : change.direction === 'up' ? IconArrowUpRight : change.direction === 'down' ? IconArrowDownRight : IconMinus;
  const color = !change || change.good === null ? 'dimmed' : change.good ? 'teal.7' : 'red.7';
  return (
    <Card withBorder padding="md" data-testid={testId}>
      <Text size="sm" c="dimmed">
        {label}
      </Text>
      <Text fz={28} fw={650} lh={1.25} mt={2}>
        {value}
      </Text>
      {sub && (
        <Text size="xs" c="dimmed">
          {sub}
        </Text>
      )}
      {change && Icon && (
        <Group gap={4} mt={4} wrap="nowrap">
          <Icon size={14} color={`var(--mantine-color-${color.replace('.', '-')})`} aria-hidden />
          <Text size="xs" c={color} fw={600} className="hms-num">
            {change.text}
          </Text>
          {vsLabel && (
            <Text size="xs" c="dimmed">
              {vsLabel}
            </Text>
          )}
        </Group>
      )}
    </Card>
  );
}
