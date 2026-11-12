import { useState } from 'react';
import { ActionIcon, Alert, Badge, Button, Chip, Drawer, Group, MultiSelect, NumberInput, Select, SimpleGrid, Stack, Switch, Table, Text, Title } from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import { IconEdit, IconPlus, IconTrash } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { useCrud, useHotelQuery } from '@/api/hooks';
import type { Hotel, PricingRule, RuleKind } from '@/api/types';
import { useAuth, useHotel } from '@/auth/AuthProvider';
import { LocalizedTextInput } from '@/components/LocalizedTextInput';
import { ActiveBadge, confirmDelete, EmptyState, SubmitButton } from '@/components/ui';
import { applyFieldErrors, errorMessage, notifyError, notifySuccess } from '@/lib/errors';
import { formatDate } from '@/lib/format';
import { type LocalizedText, pickLocalized } from '@/lib/localized';
import { useInventory } from '@/modules/reservations/shared';
import { adjustmentLabel, conditionLabel, RULE_KINDS, usePricingLookups, WEEKDAY_KEYS, weekdaysLabel } from './shared';

const KIND_COLORS: Record<RuleKind, string> = { season: 'brass', weekday: 'blue', occupancy: 'grape', long_stay: 'teal', last_minute: 'orange', early_bird: 'cyan' };
const CONDITION_FIELD: Partial<Record<RuleKind, 'min_nights' | 'max_days_before' | 'min_days_before' | 'min_occupancy'>> = {
  long_stay: 'min_nights',
  last_minute: 'max_days_before',
  early_bird: 'min_days_before',
  occupancy: 'min_occupancy',
};

interface Draft {
  id?: string;
  version?: number;
  name: LocalizedText;
  kind: RuleKind;
  priority: number;
  date_from: string | null;
  date_to: string | null;
  weekdays: string[];
  room_type_ids: string[];
  rate_plan_ids: string[];
  adjustment: PricingRule['adjustment'];
  value: number | string;
  condition: number | string;
  is_active: boolean;
}

function newDraft(kind: RuleKind): Draft {
  const defaults: Partial<Record<RuleKind, Partial<Draft>>> = {
    season: { adjustment: 'percent', value: 20 },
    weekday: { adjustment: 'percent', value: 15, weekdays: ['4', '5'] },
    occupancy: { adjustment: 'percent', value: 10, condition: 80 },
    long_stay: { adjustment: 'percent', value: -10, condition: 7 },
    last_minute: { adjustment: 'percent', value: -15, condition: 2 },
    early_bird: { adjustment: 'percent', value: -10, condition: 60 },
  };
  return {
    name: {}, kind, priority: 100, date_from: null, date_to: null, weekdays: [], room_type_ids: [], rate_plan_ids: [],
    adjustment: 'percent', value: '', condition: '', is_active: true, ...defaults[kind],
  };
}

export default function RulesTab() {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const { can } = useAuth();
  const canManage = can('pricing.manage');
  const inv = useInventory();
  const pricing = usePricingLookups();
  const rules = useHotelQuery<PricingRule[]>('pricing_rule', '/pricing-rules');
  const crud = useCrud<PricingRule>('pricing_rule', '/pricing-rules', ['pricing_rule', 'rate', 'calendar']);
  const [draft, setDraft] = useState<Draft | null>(null);

  const scope = (r: PricingRule) =>
    [
      r.room_type_ids.length ? r.room_type_ids.map((id) => inv.typeName(id)).join(', ') : null,
      r.rate_plan_ids.length ? r.rate_plan_ids.map((id) => pricing.planName(id)).join(', ') : null,
    ]
      .filter(Boolean)
      .join(' · ') || t('pricing.rules.everything');

  return (
    <Stack>
      <Group justify="space-between" align="flex-start">
        <Text size="sm" c="dimmed" maw={680}>
          {t('pricing.rules.hint')}
        </Text>
        {canManage && (
          <Select
            placeholder={t('pricing.rules.add')}
            data={RULE_KINDS.map((k) => ({ value: k, label: t(`pricing.rules.kinds.${k}`) }))}
            value={null}
            onChange={(k) => k && setDraft(newDraft(k as RuleKind))}
            leftSection={<IconPlus size={16} />}
            w={240}
            aria-label={t('pricing.rules.add')}
          />
        )}
      </Group>
      {rules.data?.length === 0 ? (
        <EmptyState title={t('pricing.rules.empty')} description={t('pricing.rules.empty_hint')} />
      ) : (
        <div className="hms-table-wrap">
          <Table miw={760}>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t('common.name')}</Table.Th>
                <Table.Th>{t('pricing.rules.when')}</Table.Th>
                <Table.Th>{t('pricing.rules.adjustment')}</Table.Th>
                <Table.Th>{t('pricing.rules.applies_to')}</Table.Th>
                <Table.Th ta="right">{t('pricing.rules.priority')}</Table.Th>
                <Table.Th>{t('common.status')}</Table.Th>
                {canManage && <Table.Th w={80} />}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {rules.data?.map((r) => (
                <Table.Tr key={r.id}>
                  <Table.Td>
                    <Text size="sm" fw={600}>
                      {pickLocalized(r.name, i18n.language, hotel.default_language)}
                    </Text>
                    <Badge size="xs" variant="light" color={KIND_COLORS[r.kind]} radius="sm">
                      {t(`pricing.rules.kinds.${r.kind}`)}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">
                      {r.date_from || r.date_to ? `${formatDate(r.date_from, i18n.language)} → ${formatDate(r.date_to, i18n.language)}` : t('pricing.rules.any_date')}
                    </Text>
                    <Text size="xs" c="dimmed">
                      {[weekdaysLabel(r.weekdays, t), conditionLabel(r, t)].filter(Boolean).join(' · ')}
                    </Text>
                  </Table.Td>
                  <Table.Td className="hms-num">
                    <Text size="sm" fw={600} c={Number(r.value) < 0 ? 'teal.7' : undefined}>
                      {adjustmentLabel(r.adjustment, r.value, hotel.currency_code, i18n.language)}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm" lineClamp={2}>
                      {scope(r)}
                    </Text>
                  </Table.Td>
                  <Table.Td ta="right" className="hms-num">
                    {r.priority}
                  </Table.Td>
                  <Table.Td>
                    <ActiveBadge active={r.is_active} />
                  </Table.Td>
                  {canManage && (
                    <Table.Td>
                      <Group gap={4} justify="flex-end" wrap="nowrap">
                        <ActionIcon
                          variant="subtle"
                          aria-label={t('common.edit')}
                          onClick={() => {
                            const field = CONDITION_FIELD[r.kind];
                            setDraft({ ...r, weekdays: r.weekdays.map(String), condition: field ? (r.conditions[field] ?? '') : '' });
                          }}
                        >
                          <IconEdit size={16} />
                        </ActionIcon>
                        <ActionIcon
                          variant="subtle"
                          color="red"
                          aria-label={t('common.delete')}
                          onClick={() =>
                            confirmDelete({
                              title: t('pricing.rules.delete', { name: pickLocalized(r.name, i18n.language) }),
                              onConfirm: () => crud.remove.mutateAsync(r.id).then(() => notifySuccess(t('common.deleted')), notifyError),
                            })
                          }
                        >
                          <IconTrash size={16} />
                        </ActionIcon>
                      </Group>
                    </Table.Td>
                  )}
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </div>
      )}
      {draft && <RuleDrawer draft={draft} crud={crud} onClose={() => setDraft(null)} />}
    </Stack>
  );
}

function RuleDrawer({ draft, crud, onClose }: { draft: Draft; crud: ReturnType<typeof useCrud<PricingRule>>; onClose: () => void }) {
  const { t } = useTranslation();
  const hotel = useHotel();
  const profile = useHotelQuery<Hotel>('hotel', '');
  const inv = useInventory();
  const pricing = usePricingLookups();
  const [v, setV] = useState<Draft>(draft);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const languages = profile.data?.supported_languages ?? [hotel.default_language];
  const set = (patch: Partial<Draft>) => setV((x) => ({ ...x, ...patch }));
  const conditionField = CONDITION_FIELD[v.kind];
  const isDiscount = v.kind === 'long_stay' || v.kind === 'last_minute' || v.kind === 'early_bird';

  const submit = async () => {
    setErrors({});
    setFormError(null);
    const { id, version, condition, kind, ...rest } = v;
    const body: Record<string, unknown> = {
      ...rest,
      weekdays: rest.weekdays.map(Number),
      value: String(rest.value),
      conditions: conditionField && condition !== '' ? { [conditionField]: Number(condition) } : {},
    };
    try {
      if (id) await crud.update.mutateAsync({ id, body: { ...body, version } });
      else await crud.create.mutateAsync({ ...body, kind } as never);
      notifySuccess(t('common.saved'));
      onClose();
    } catch (err) {
      const map: Record<string, string> = {};
      if (!applyFieldErrors(err, (k, m) => (map[k] = m))) setFormError(errorMessage(err));
      else setFormError(errorMessage(err));
      setErrors(map);
    }
  };

  return (
    <Drawer opened onClose={onClose} title={<Title order={3}>{t(`pricing.rules.kinds.${v.kind}`)}</Title>} size="lg">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <Stack>
          <Text size="sm" c="dimmed">
            {t(`pricing.rules.kind_hints.${v.kind}`)}
          </Text>
          {formError && <Alert color="red">{formError}</Alert>}
          <LocalizedTextInput label={t('common.name')} required languages={languages} value={v.name} onChange={(x) => set({ name: x })} error={errors.name} />
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <DatePickerInput label={t('pricing.rules.date_from')} clearable required={v.kind === 'season'} value={v.date_from} onChange={(x) => set({ date_from: x })} error={errors.date_from} />
            <DatePickerInput label={t('pricing.rules.date_to')} clearable required={v.kind === 'season'} value={v.date_to} onChange={(x) => set({ date_to: x })} />
          </SimpleGrid>
          <div>
            <Text size="sm" fw={500} mb={4}>
              {t('pricing.bulk.weekdays')}
              {v.kind === 'weekday' && <Text span c="red"> *</Text>}
            </Text>
            <Chip.Group multiple value={v.weekdays} onChange={(x) => set({ weekdays: x })}>
              <Group gap={6}>
                {WEEKDAY_KEYS.map((k, i) => (
                  <Chip key={k} value={String(i)} size="xs">
                    {t(`pricing.weekday_short.${k}`)}
                  </Chip>
                ))}
              </Group>
            </Chip.Group>
            <Text size="xs" c={errors.weekdays ? 'red' : 'dimmed'} mt={4}>
              {errors.weekdays ?? t('pricing.rules.weekdays_hint')}
            </Text>
          </div>
          {conditionField && (
            <NumberInput
              label={t(`pricing.rules.condition.${conditionField}`)}
              min={0}
              max={conditionField === 'min_occupancy' ? 100 : 730}
              value={v.condition}
              onChange={(x) => set({ condition: x })}
              required
              error={errors.conditions}
            />
          )}
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <Select
              label={t('pricing.rules.adjustment')}
              allowDeselect={false}
              data={(['percent', 'amount', 'set'] as const).filter((m) => !(isDiscount && m === 'set')).map((m) => ({ value: m, label: t(`pricing.rules.adjustments.${m}`) }))}
              value={v.adjustment}
              onChange={(x) => x && set({ adjustment: x as Draft['adjustment'] })}
            />
            <NumberInput
              label={t('pricing.rules.value')}
              description={v.adjustment === 'percent' ? t('pricing.bulk.percent_hint') : v.adjustment === 'set' ? hotel.currency_code : t('pricing.bulk.amount_hint', { currency: hotel.currency_code })}
              decimalScale={2}
              value={v.value}
              onChange={(x) => set({ value: x })}
              required
              error={errors.value}
            />
          </SimpleGrid>
          <MultiSelect label={t('pricing.rules.room_types')} placeholder={t('pricing.plans.all_categories')} data={inv.types.map((rt) => ({ value: rt.id, label: inv.typeName(rt.id) }))} value={v.room_type_ids} onChange={(x) => set({ room_type_ids: x })} />
          <MultiSelect label={t('pricing.rules.rate_plans')} placeholder={t('pricing.rules.all_plans')} data={pricing.plans.map((p) => ({ value: p.id, label: pricing.planName(p.id) }))} value={v.rate_plan_ids} onChange={(x) => set({ rate_plan_ids: x })} />
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <NumberInput label={t('pricing.rules.priority')} description={t('pricing.rules.priority_hint')} min={0} max={10000} value={v.priority} onChange={(x) => set({ priority: Number(x) || 0 })} />
            <Switch mt={28} label={t('common.active')} checked={v.is_active} onChange={(e) => set({ is_active: e.currentTarget.checked })} />
          </SimpleGrid>
          <Group justify="flex-end" mt="md">
            <Button variant="default" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <SubmitButton loading={crud.create.isPending || crud.update.isPending}>{t('common.save')}</SubmitButton>
          </Group>
        </Stack>
      </form>
    </Drawer>
  );
}
