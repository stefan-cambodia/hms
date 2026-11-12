import { useState } from 'react';
import { ActionIcon, Alert, Badge, Button, Drawer, Group, MultiSelect, NumberInput, Select, SimpleGrid, Stack, Switch, Table, Text, TextInput, Title } from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import { IconEdit, IconPlus, IconTrash } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { useCrud, useHotelQuery } from '@/api/hooks';
import type { Hotel, RatePlan } from '@/api/types';
import { useAuth, useHotel } from '@/auth/AuthProvider';
import { LocalizedTextInput } from '@/components/LocalizedTextInput';
import { ActiveBadge, confirmDelete, SubmitButton } from '@/components/ui';
import { applyFieldErrors, errorMessage, notifyError, notifySuccess } from '@/lib/errors';
import { formatDate } from '@/lib/format';
import type { LocalizedText } from '@/lib/localized';
import { useInventory } from '@/modules/reservations/shared';
import { derivationLabel, MEAL_PLANS, policySummary, usePricingLookups } from './shared';

interface Draft {
  id?: string;
  version?: number;
  code: string;
  name: LocalizedText;
  description: LocalizedText;
  meal_plan: RatePlan['meal_plan'];
  is_refundable: boolean;
  cancellation_policy_id: string | null;
  parent_rate_plan_id: string | null;
  derive_mode: RatePlan['derive_mode'];
  derive_value: number | string;
  room_type_ids: string[];
  valid_from: string | null;
  valid_to: string | null;
  min_advance_days: number | string;
  max_advance_days: number | string;
  is_default: boolean;
  sort_order: number;
  is_active: boolean;
}

const EMPTY: Draft = {
  code: '', name: {}, description: {}, meal_plan: 'room_only', is_refundable: true, cancellation_policy_id: null, parent_rate_plan_id: null,
  derive_mode: null, derive_value: '', room_type_ids: [], valid_from: null, valid_to: null, min_advance_days: '', max_advance_days: '',
  is_default: false, sort_order: 0, is_active: true,
};

export default function RatePlansTab() {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const { can } = useAuth();
  const canManage = can('pricing.manage');
  const inv = useInventory();
  const pricing = usePricingLookups();
  const crud = useCrud<RatePlan>('rate_plan', '/rate-plans', ['rate_plan', 'rate', 'calendar']);
  const [draft, setDraft] = useState<Draft | null>(null);

  return (
    <Stack>
      <Group justify="space-between">
        <Text size="sm" c="dimmed" maw={680}>
          {t('pricing.plans.hint')}
        </Text>
        {canManage && (
          <Button leftSection={<IconPlus size={16} />} onClick={() => setDraft({ ...EMPTY, cancellation_policy_id: pricing.policies.find((p) => p.code === 'FLEX')?.id ?? null })}>
            {t('pricing.plans.add')}
          </Button>
        )}
      </Group>
      <div className="hms-table-wrap">
        <Table miw={760}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t('common.name')}</Table.Th>
              <Table.Th>{t('pricing.plans.meal_plan')}</Table.Th>
              <Table.Th>{t('pricing.plans.price')}</Table.Th>
              <Table.Th>{t('pricing.plans.cancellation')}</Table.Th>
              <Table.Th>{t('pricing.plans.categories')}</Table.Th>
              <Table.Th>{t('common.status')}</Table.Th>
              {canManage && <Table.Th w={80} />}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {pricing.plans.map((p) => (
              <Table.Tr key={p.id}>
                <Table.Td>
                  <Group gap={6} wrap="nowrap">
                    <Text size="sm" fw={600}>
                      {pricing.planName(p.id)}
                    </Text>
                    {p.is_default && (
                      <Badge size="xs" variant="filled">
                        {t('pricing.plans.default')}
                      </Badge>
                    )}
                  </Group>
                  <Text size="xs" c="dimmed">
                    {p.code}
                    {p.valid_from || p.valid_to ? ` · ${formatDate(p.valid_from, i18n.language)} → ${formatDate(p.valid_to, i18n.language)}` : ''}
                  </Text>
                </Table.Td>
                <Table.Td>{t(`pricing.meal_plans.${p.meal_plan}`)}</Table.Td>
                <Table.Td>
                  <Text size="sm">{p.parent_rate_plan_id ? derivationLabel(p, pricing.planName(p.parent_rate_plan_id), hotel.currency_code, i18n.language, t) : t('pricing.plans.own_rates')}</Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{p.is_refundable ? policySummary(p.cancellation_policy_id ? pricing.policyById.get(p.cancellation_policy_id) : undefined, t) : t('pricing.plans.non_refundable')}</Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{p.room_type_ids.length ? p.room_type_ids.map((id) => inv.typeName(id)).join(', ') : t('pricing.plans.all_categories')}</Text>
                </Table.Td>
                <Table.Td>
                  <ActiveBadge active={p.is_active} />
                </Table.Td>
                {canManage && (
                  <Table.Td>
                    <Group gap={4} justify="flex-end" wrap="nowrap">
                      <ActionIcon
                        variant="subtle"
                        aria-label={t('common.edit')}
                        onClick={() =>
                          setDraft({
                            ...p,
                            derive_value: p.derive_value ?? '',
                            min_advance_days: p.min_advance_days ?? '',
                            max_advance_days: p.max_advance_days ?? '',
                          })
                        }
                      >
                        <IconEdit size={16} />
                      </ActionIcon>
                      {!p.is_default && (
                        <ActionIcon
                          variant="subtle"
                          color="red"
                          aria-label={t('common.delete')}
                          onClick={() =>
                            confirmDelete({
                              title: t('pricing.plans.delete', { name: pricing.planName(p.id) }),
                              onConfirm: () => crud.remove.mutateAsync(p.id).then(() => notifySuccess(t('common.deleted')), notifyError),
                            })
                          }
                        >
                          <IconTrash size={16} />
                        </ActionIcon>
                      )}
                    </Group>
                  </Table.Td>
                )}
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </div>
      {draft && <PlanDrawer draft={draft} crud={crud} onClose={() => setDraft(null)} />}
    </Stack>
  );
}

function PlanDrawer({ draft, crud, onClose }: { draft: Draft; crud: ReturnType<typeof useCrud<RatePlan>>; onClose: () => void }) {
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
  const derived = !!v.parent_rate_plan_id;

  const submit = async () => {
    setErrors({});
    setFormError(null);
    const { id, version, ...rest } = v;
    const body = {
      ...rest,
      derive_mode: derived ? rest.derive_mode ?? 'percent' : null,
      derive_value: derived && rest.derive_value !== '' ? String(rest.derive_value) : null,
      min_advance_days: rest.min_advance_days === '' ? null : Number(rest.min_advance_days),
      max_advance_days: rest.max_advance_days === '' ? null : Number(rest.max_advance_days),
      cancellation_policy_id: rest.is_refundable ? rest.cancellation_policy_id : (pricing.policies.find((p) => p.code === 'NONREF')?.id ?? rest.cancellation_policy_id),
    };
    try {
      if (id) await crud.update.mutateAsync({ id, body: { ...body, version } });
      else await crud.create.mutateAsync(body as never);
      notifySuccess(t('common.saved'));
      onClose();
    } catch (err) {
      const map: Record<string, string> = {};
      if (!applyFieldErrors(err, (k, m) => (map[k] = m))) setFormError(errorMessage(err));
      setErrors(map);
    }
  };

  return (
    <Drawer opened onClose={onClose} title={<Title order={3}>{draft.id ? t('pricing.plans.edit') : t('pricing.plans.add')}</Title>} size="xl">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <Stack>
          {formError && <Alert color="red">{formError}</Alert>}
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <TextInput label={t('common.code')} description={t('common.code_hint')} required value={v.code} onChange={(e) => set({ code: e.currentTarget.value })} error={errors.code} />
            <Select
              label={t('pricing.plans.meal_plan')}
              allowDeselect={false}
              data={MEAL_PLANS.map((m) => ({ value: m, label: t(`pricing.meal_plans.${m}`) }))}
              value={v.meal_plan}
              onChange={(x) => x && set({ meal_plan: x as Draft['meal_plan'] })}
            />
          </SimpleGrid>
          <LocalizedTextInput label={t('common.name')} required languages={languages} value={v.name} onChange={(x) => set({ name: x })} error={errors.name} />
          <LocalizedTextInput label={t('common.description')} multiline languages={languages} value={v.description} onChange={(x) => set({ description: x })} />

          <Title order={5}>{t('pricing.plans.price')}</Title>
          <Select
            label={t('pricing.plans.based_on')}
            description={t('pricing.plans.based_on_hint')}
            clearable
            placeholder={t('pricing.plans.own_rates')}
            data={pricing.plans.filter((p) => p.id !== v.id).map((p) => ({ value: p.id, label: pricing.planName(p.id) }))}
            value={v.parent_rate_plan_id}
            onChange={(x) => set({ parent_rate_plan_id: x, derive_mode: x ? (v.derive_mode ?? 'percent') : null })}
            error={errors.parent_rate_plan_id}
          />
          {derived && (
            <SimpleGrid cols={{ base: 1, sm: 2 }}>
              <Select
                label={t('pricing.plans.adjustment')}
                allowDeselect={false}
                data={(['percent', 'amount', 'amount_per_person'] as const).map((m) => ({ value: m, label: t(`pricing.plans.derive_modes.${m}`) }))}
                value={v.derive_mode ?? 'percent'}
                onChange={(x) => set({ derive_mode: x as Draft['derive_mode'] })}
              />
              <NumberInput
                label={t('pricing.plans.adjustment_value')}
                description={v.derive_mode === 'percent' ? t('pricing.bulk.percent_hint') : t('pricing.bulk.amount_hint', { currency: hotel.currency_code })}
                decimalScale={2}
                value={v.derive_value}
                onChange={(x) => set({ derive_value: x })}
                required
                error={errors.derive_value || errors.derive_mode}
              />
            </SimpleGrid>
          )}

          <Title order={5}>{t('pricing.plans.cancellation')}</Title>
          <Switch label={t('pricing.plans.refundable')} checked={v.is_refundable} onChange={(e) => set({ is_refundable: e.currentTarget.checked })} />
          {v.is_refundable && (
            <Select
              label={t('pricing.plans.policy')}
              clearable
              data={pricing.policies.filter((p) => p.is_active).map((p) => ({ value: p.id, label: `${pricing.policyName(p.id)} — ${policySummary(p, t)}` }))}
              value={v.cancellation_policy_id}
              onChange={(x) => set({ cancellation_policy_id: x })}
            />
          )}

          <Title order={5}>{t('pricing.plans.availability')}</Title>
          <MultiSelect
            label={t('pricing.plans.categories')}
            description={t('pricing.plans.categories_hint')}
            data={inv.types.map((rt) => ({ value: rt.id, label: inv.typeName(rt.id) }))}
            value={v.room_type_ids}
            onChange={(x) => set({ room_type_ids: x })}
            error={errors.room_type_ids}
          />
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <DatePickerInput label={t('pricing.plans.valid_from')} clearable value={v.valid_from} onChange={(x) => set({ valid_from: x })} />
            <DatePickerInput label={t('pricing.plans.valid_to')} clearable value={v.valid_to} onChange={(x) => set({ valid_to: x })} />
            <NumberInput label={t('pricing.plans.min_advance')} description={t('pricing.plans.min_advance_hint')} min={0} max={1000} value={v.min_advance_days} onChange={(x) => set({ min_advance_days: x })} />
            <NumberInput label={t('pricing.plans.max_advance')} description={t('pricing.plans.max_advance_hint')} min={0} max={1000} value={v.max_advance_days} onChange={(x) => set({ max_advance_days: x })} />
          </SimpleGrid>
          <Group>
            <Switch label={t('pricing.plans.is_default')} checked={v.is_default} disabled={draft.is_default} onChange={(e) => set({ is_default: e.currentTarget.checked })} />
            <Switch label={t('common.active')} checked={v.is_active} disabled={v.is_default} onChange={(e) => set({ is_active: e.currentTarget.checked })} />
          </Group>
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
