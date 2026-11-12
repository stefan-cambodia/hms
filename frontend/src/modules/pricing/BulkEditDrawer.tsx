import { useState } from 'react';
import { Alert, Button, Chip, Divider, Drawer, Group, MultiSelect, NumberInput, SegmentedControl, Stack, Text, Title } from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { api } from '@/api/client';
import { hotelKey } from '@/api/realtime';
import { useHotel } from '@/auth/AuthProvider';
import { SubmitButton } from '@/components/ui';
import { daysBetween } from '@/lib/dates';
import { errorMessage, notifySuccess } from '@/lib/errors';
import { useInventory } from '@/modules/reservations/shared';
import { usePricingLookups, WEEKDAY_KEYS } from './shared';

export interface BulkDraft {
  rate_plan_ids: string[];
  room_type_ids: string[];
  start: string;
  end: string; // inclusive
}

type PriceMode = 'none' | 'set' | 'percent' | 'amount' | 'clear';
type StayMode = 'none' | 'set' | 'clear';
type Flag = 'none' | 'on' | 'off';

export function BulkEditDrawer({ draft, onClose }: { draft: BulkDraft; onClose: () => void }) {
  const { t } = useTranslation();
  const hotel = useHotel();
  const qc = useQueryClient();
  const inv = useInventory();
  const pricing = usePricingLookups();
  const [plans, setPlans] = useState(draft.rate_plan_ids);
  const [types, setTypes] = useState(draft.room_type_ids);
  const [range, setRange] = useState<[string | null, string | null]>([draft.start, draft.end]);
  const [weekdays, setWeekdays] = useState<string[]>([]);
  const [priceMode, setPriceMode] = useState<PriceMode>('none');
  const [priceValue, setPriceValue] = useState<number | string>('');
  const [minMode, setMinMode] = useState<StayMode>('none');
  const [minStay, setMinStay] = useState<number | string>(2);
  const [maxMode, setMaxMode] = useState<StayMode>('none');
  const [maxStay, setMaxStay] = useState<number | string>(14);
  const [closed, setClosed] = useState<Flag>('none');
  const [cta, setCta] = useState<Flag>('none');
  const [ctd, setCtd] = useState<Flag>('none');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [start, end] = range;
  const dayCount = start && end ? daysBetween(start, end) + 1 : 0;
  const restrictions: Record<string, unknown> = {};
  if (minMode !== 'none') restrictions.min_stay = minMode === 'set' ? Number(minStay) : null;
  if (maxMode !== 'none') restrictions.max_stay = maxMode === 'set' ? Number(maxStay) : null;
  if (closed !== 'none') restrictions.closed = closed === 'on';
  if (cta !== 'none') restrictions.closed_to_arrival = cta === 'on';
  if (ctd !== 'none') restrictions.closed_to_departure = ctd === 'on';
  const hasPrice = priceMode !== 'none' && (priceMode === 'clear' || priceValue !== '');
  const valid = plans.length > 0 && types.length > 0 && !!start && !!end && end >= start && (hasPrice || Object.keys(restrictions).length > 0);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await api.post<{ cells_changed: number }>(`/hotels/${hotel.id}/rates/bulk`, {
        rate_plan_ids: plans,
        room_type_ids: types,
        start,
        end,
        weekdays: weekdays.map(Number),
        price: hasPrice ? { mode: priceMode, value: priceMode === 'clear' ? null : String(priceValue) } : null,
        restrictions: Object.keys(restrictions).length ? restrictions : null,
      });
      for (const e of ['rate', 'calendar']) void qc.invalidateQueries({ queryKey: hotelKey(hotel.id, e) });
      notifySuccess(t('pricing.bulk.done', { count: res.cells_changed }));
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const flagControl = (label: string, value: Flag, set: (f: Flag) => void, onLabel: string, offLabel: string) => (
    <div>
      <Text size="sm" fw={500} mb={4}>
        {label}
      </Text>
      <SegmentedControl
        size="xs"
        value={value}
        onChange={(v) => set(v as Flag)}
        data={[
          { value: 'none', label: t('pricing.bulk.no_change') },
          { value: 'on', label: onLabel },
          { value: 'off', label: offLabel },
        ]}
      />
    </div>
  );

  return (
    <Drawer opened onClose={onClose} title={<Title order={3}>{t('pricing.grid.edit_rates')}</Title>} size="lg">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (valid) void submit();
        }}
      >
        <Stack>
          {error && <Alert color="red">{error}</Alert>}
          <MultiSelect label={t('pricing.bulk.rate_plans')} data={pricing.plans.map((p) => ({ value: p.id, label: pricing.planName(p.id) }))} value={plans} onChange={setPlans} required />
          <MultiSelect label={t('pricing.bulk.room_types')} data={inv.types.filter((rt) => rt.is_active).map((rt) => ({ value: rt.id, label: inv.typeName(rt.id) }))} value={types} onChange={setTypes} required />
          <DatePickerInput type="range" label={t('pricing.bulk.dates')} description={dayCount ? t('pricing.bulk.days', { count: dayCount }) : undefined} value={range} onChange={(v) => setRange([v[0], v[1]])} allowSingleDateInRange required />
          <div>
            <Text size="sm" fw={500} mb={4}>
              {t('pricing.bulk.weekdays')}
            </Text>
            <Chip.Group multiple value={weekdays} onChange={setWeekdays}>
              <Group gap={6}>
                {WEEKDAY_KEYS.map((k, i) => (
                  <Chip key={k} value={String(i)} size="xs">
                    {t(`pricing.weekday_short.${k}`)}
                  </Chip>
                ))}
              </Group>
            </Chip.Group>
            <Text size="xs" c="dimmed" mt={4}>
              {t('pricing.bulk.weekdays_hint')}
            </Text>
          </div>

          <Divider label={t('pricing.bulk.price')} labelPosition="left" />
          <SegmentedControl
            value={priceMode}
            onChange={(v) => setPriceMode(v as PriceMode)}
            data={(['none', 'set', 'percent', 'amount', 'clear'] as const).map((m) => ({ value: m, label: t(`pricing.bulk.price_modes.${m}`) }))}
            fullWidth
            size="xs"
          />
          {(priceMode === 'set' || priceMode === 'percent' || priceMode === 'amount') && (
            <NumberInput
              label={t(`pricing.bulk.value_${priceMode}`)}
              description={priceMode === 'set' ? hotel.currency_code : priceMode === 'amount' ? t('pricing.bulk.amount_hint', { currency: hotel.currency_code }) : t('pricing.bulk.percent_hint')}
              value={priceValue}
              onChange={setPriceValue}
              decimalScale={2}
              min={priceMode === 'set' ? 0 : priceMode === 'percent' ? -99 : undefined}
              required
            />
          )}
          {priceMode === 'clear' && (
            <Text size="xs" c="dimmed">
              {t('pricing.bulk.clear_hint')}
            </Text>
          )}

          <Divider label={t('pricing.bulk.restrictions')} labelPosition="left" />
          <Group align="flex-end" gap="sm">
            <div>
              <Text size="sm" fw={500} mb={4}>
                {t('pricing.bulk.min_stay')}
              </Text>
              <SegmentedControl size="xs" value={minMode} onChange={(v) => setMinMode(v as StayMode)} data={[{ value: 'none', label: t('pricing.bulk.no_change') }, { value: 'set', label: t('pricing.bulk.set') }, { value: 'clear', label: t('pricing.bulk.remove') }]} />
            </div>
            {minMode === 'set' && <NumberInput aria-label={t('pricing.bulk.min_stay')} w={90} min={1} max={365} value={minStay} onChange={setMinStay} />}
          </Group>
          <Group align="flex-end" gap="sm">
            <div>
              <Text size="sm" fw={500} mb={4}>
                {t('pricing.bulk.max_stay')}
              </Text>
              <SegmentedControl size="xs" value={maxMode} onChange={(v) => setMaxMode(v as StayMode)} data={[{ value: 'none', label: t('pricing.bulk.no_change') }, { value: 'set', label: t('pricing.bulk.set') }, { value: 'clear', label: t('pricing.bulk.remove') }]} />
            </div>
            {maxMode === 'set' && <NumberInput aria-label={t('pricing.bulk.max_stay')} w={90} min={1} max={365} value={maxStay} onChange={setMaxStay} />}
          </Group>
          {flagControl(t('pricing.bulk.stop_sell'), closed, setClosed, t('pricing.bulk.close'), t('pricing.bulk.open'))}
          {flagControl(t('pricing.grid.cta_long'), cta, setCta, t('pricing.bulk.yes'), t('pricing.bulk.no'))}
          {flagControl(t('pricing.grid.ctd_long'), ctd, setCtd, t('pricing.bulk.yes'), t('pricing.bulk.no'))}
          <Text size="xs" c="dimmed">
            {t('pricing.bulk.existing_bookings_hint')}
          </Text>
          <Group justify="flex-end" mt="md">
            <Button variant="default" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <SubmitButton loading={busy} disabled={!valid}>
              {t('pricing.bulk.apply')}
            </SubmitButton>
          </Group>
        </Stack>
      </form>
    </Drawer>
  );
}
