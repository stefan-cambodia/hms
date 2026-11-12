import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router';
import { ActionIcon, Badge, Box, Button, Card, Group, Loader, SegmentedControl, Select, Stack, Text, Tooltip } from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import { IconAdjustmentsDollar, IconChevronLeft, IconChevronRight } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { useHotelQuery } from '@/api/hooks';
import type { GridCell, RateGrid } from '@/api/types';
import { useAuth, useHotel } from '@/auth/AuthProvider';
import { EmptyState } from '@/components/ui';
import { addDays, dayLabel, hotelToday, weekday } from '@/lib/dates';
import { formatMoney } from '@/lib/format';
import { useInventory } from '@/modules/reservations/shared';
import { BulkEditDrawer, type BulkDraft } from './BulkEditDrawer';
import { usePricingLookups } from './shared';

const LABEL_W = 180;

export default function RateGridTab() {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const { can } = useAuth();
  const canManage = can('pricing.manage');
  const inv = useInventory();
  const pricing = usePricingLookups();
  const today = hotelToday(hotel.timezone);
  // View state in the URL: bookmarkable and shareable.
  const [params, setParams] = useSearchParams();
  const update = (patch: Record<string, string>) =>
    setParams((p) => {
      const out = new URLSearchParams(p);
      for (const [k, v] of Object.entries(patch)) out.set(k, v);
      return out;
    }, { replace: true });
  const planId = params.get('plan') ?? pricing.defaultPlan?.id ?? null;
  const start = /^\d{4}-\d{2}-\d{2}$/.test(params.get('start') ?? '') ? params.get('start')! : today;
  const days: 14 | 31 = params.get('days') === '31' ? 31 : 14;
  const setPlanId = (v: string | null) => v && update({ plan: v });
  const setStart = (v: string) => update({ start: v });
  const setDays = (v: 14 | 31) => update({ days: String(v) });
  const [draft, setDraft] = useState<BulkDraft | null>(null);

  const end = addDays(start, days);
  const grid = useHotelQuery<RateGrid>('rate', '/rates/grid', { rate_plan_id: planId, start, end }, !!planId);
  const cells = useMemo(() => {
    const m = new Map<string, GridCell>();
    for (const c of grid.data?.cells ?? []) m.set(`${c.room_type_id}|${c.date}`, c);
    return m;
  }, [grid.data]);
  const dates = useMemo(() => Array.from({ length: days }, (_, i) => addDays(start, i)), [start, days]);
  const W = days === 14 ? 84 : 66;
  const plan = planId ? pricing.planById.get(planId) : undefined;

  return (
    <Stack>
      <Card padding="sm">
        <Group justify="space-between" wrap="wrap" gap="sm">
          <Group gap="xs" wrap="wrap">
            <Select
              aria-label={t('pricing.grid.rate_plan')}
              data={pricing.plans.map((p) => ({ value: p.id, label: `${pricing.planName(p.id)}${p.is_default ? ` (${t('pricing.plans.default')})` : ''}` }))}
              value={planId}
              onChange={setPlanId}
              allowDeselect={false}
              w={240}
            />
            <ActionIcon variant="default" size="lg" aria-label={t('calendar.previous')} onClick={() => setStart(addDays(start, -days))}>
              <IconChevronLeft size={18} />
            </ActionIcon>
            <Button variant="default" onClick={() => setStart(today)}>
              {t('calendar.today')}
            </Button>
            <ActionIcon variant="default" size="lg" aria-label={t('calendar.next')} onClick={() => setStart(addDays(start, days))}>
              <IconChevronRight size={18} />
            </ActionIcon>
            <DatePickerInput value={start} onChange={(v) => v && setStart(v)} valueFormat="D MMM YYYY" w={150} aria-label={t('calendar.start_date')} />
            <SegmentedControl value={String(days)} onChange={(v) => setDays(Number(v) as 14 | 31)} data={[{ value: '14', label: t('calendar.range.two_weeks') }, { value: '31', label: t('calendar.range.month') }]} />
            {grid.isFetching && <Loader size="xs" />}
          </Group>
          {canManage && planId && (
            <Button
              leftSection={<IconAdjustmentsDollar size={16} />}
              onClick={() => setDraft({ rate_plan_ids: [planId], room_type_ids: grid.data?.room_type_ids ?? [], start, end: addDays(end, -1) })}
            >
              {t('pricing.grid.edit_rates')}
            </Button>
          )}
        </Group>
      </Card>

      {plan?.parent_rate_plan_id && (
        <Text size="sm" c="dimmed">
          {t('pricing.grid.derived_hint', { parent: pricing.planName(plan.parent_rate_plan_id) })}
        </Text>
      )}

      {grid.data && grid.data.room_type_ids.length === 0 ? (
        <EmptyState title={t('pricing.grid.no_categories')} />
      ) : (
        <Card padding={0}>
          <Box style={{ overflow: 'auto' }}>
            <Box style={{ width: LABEL_W + days * W, minWidth: '100%' }}>
              <div style={{ display: 'flex', borderBottom: '1px solid var(--mantine-color-default-border)', position: 'sticky', top: 0, background: 'var(--mantine-color-body)', zIndex: 2 }}>
                <div style={{ width: LABEL_W, flex: 'none', position: 'sticky', left: 0, background: 'var(--mantine-color-body)', borderRight: '1px solid var(--mantine-color-default-border)' }} />
                {dates.map((d) => {
                  const l = dayLabel(d, i18n.language);
                  return (
                    <div key={d} style={{ width: W, flex: 'none', textAlign: 'center', padding: '6px 0', background: d === today ? 'var(--mantine-color-lagoon-light)' : weekday(d) >= 5 ? 'var(--mantine-color-default-hover)' : undefined }}>
                      <Text size="xs" c="dimmed">
                        {l.weekday}
                      </Text>
                      <Text size="sm" fw={600} className="hms-num">
                        {l.day} {l.day === '1' || d === start ? l.month : ''}
                      </Text>
                    </div>
                  );
                })}
              </div>
              {(grid.data?.room_type_ids ?? []).map((typeId) => (
                <div key={typeId} style={{ display: 'flex', borderBottom: '1px solid var(--mantine-color-default-border)' }} data-rate-row={inv.typeById.get(typeId)?.code}>
                  <div style={{ width: LABEL_W, flex: 'none', position: 'sticky', left: 0, zIndex: 1, background: 'var(--mantine-color-body)', padding: '8px 12px', borderRight: '1px solid var(--mantine-color-default-border)' }}>
                    <Text size="sm" fw={600} lineClamp={2}>
                      {inv.typeName(typeId)}
                    </Text>
                    <Text size="xs" c="dimmed">
                      {t('pricing.grid.base', { price: formatMoney(inv.typeById.get(typeId)?.base_price, hotel.currency_code, i18n.language) })}
                    </Text>
                  </div>
                  {dates.map((d) => {
                    const c = cells.get(`${typeId}|${d}`);
                    return (
                      <RateCell
                        key={d}
                        cell={c}
                        width={W}
                        weekend={weekday(d) >= 5}
                        currency={hotel.currency_code}
                        onClick={canManage && planId ? () => setDraft({ rate_plan_ids: [planId], room_type_ids: [typeId], start: d, end: d }) : undefined}
                      />
                    );
                  })}
                </div>
              ))}
            </Box>
          </Box>
        </Card>
      )}

      <Group gap="md" wrap="wrap">
        <Text size="xs" c="dimmed">
          <b>{formatMoney(100, hotel.currency_code, i18n.language)}</b> {t('pricing.grid.legend_explicit')} · {formatMoney(100, hotel.currency_code, i18n.language)}{' '}
          {t('pricing.grid.legend_computed')}
        </Text>
        <Badge size="xs" color="red" variant="filled">
          {t('pricing.grid.closed')}
        </Badge>
        <Text size="xs" c="dimmed">
          {t('pricing.grid.legend_restrictions')}
        </Text>
      </Group>

      {draft && <BulkEditDrawer draft={draft} onClose={() => setDraft(null)} />}
    </Stack>
  );
}

function RateCell({ cell, width, weekend, currency, onClick }: { cell?: GridCell; width: number; weekend: boolean; currency: string; onClick?: () => void }) {
  const { t, i18n } = useTranslation();
  if (!cell) return <div style={{ width, flex: 'none' }} />;
  const tags = [
    cell.min_stay ? `≥${cell.min_stay}` : null,
    cell.max_stay ? `≤${cell.max_stay}` : null,
    cell.closed_to_arrival ? t('pricing.grid.cta') : null,
    cell.closed_to_departure ? t('pricing.grid.ctd') : null,
  ].filter(Boolean);
  const tooltip = [
    t(`pricing.grid.source.${cell.source}`),
    t('pricing.grid.available', { count: cell.available }),
    cell.min_stay ? t('pricing.grid.min_stay', { count: cell.min_stay }) : null,
    cell.max_stay ? t('pricing.grid.max_stay', { count: cell.max_stay }) : null,
    cell.closed_to_arrival ? t('pricing.grid.cta_long') : null,
    cell.closed_to_departure ? t('pricing.grid.ctd_long') : null,
    cell.restrictions_inherited ? t('pricing.grid.inherited') : null,
  ]
    .filter(Boolean)
    .join(' · ');
  return (
    <Tooltip label={tooltip} openDelay={400} multiline maw={260}>
      <div
        role={onClick ? 'button' : undefined}
        tabIndex={onClick ? 0 : undefined}
        data-rate-cell={cell.date}
        onClick={onClick}
        onKeyDown={(e) => e.key === 'Enter' && onClick?.()}
        style={{
          width,
          flex: 'none',
          padding: '6px 4px',
          textAlign: 'center',
          cursor: onClick ? 'pointer' : undefined,
          borderRight: '1px solid var(--mantine-color-default-border)',
          background: cell.closed ? 'color-mix(in srgb, var(--mantine-color-red-6) 16%, var(--mantine-color-body))' : weekend ? 'var(--mantine-color-default-hover)' : undefined,
          opacity: cell.restrictions_inherited ? 0.85 : 1,
        }}
      >
        <Text size="sm" fw={cell.explicit ? 750 : 400} className="hms-num" td={cell.closed ? 'line-through' : undefined} truncate>
          {formatMoney(cell.price, currency, i18n.language)}
        </Text>
        <Text size="10px" c={cell.available <= 0 ? 'red' : 'dimmed'} className="hms-num">
          {cell.closed ? t('pricing.grid.closed') : t('pricing.grid.left', { count: cell.available })}
        </Text>
        {tags.length > 0 && (
          <Text size="10px" fw={700} c="brass.8" truncate>
            {tags.join(' ')}
          </Text>
        )}
      </div>
    </Tooltip>
  );
}
