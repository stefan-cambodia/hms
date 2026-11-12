import { useState } from 'react';
import { ActionIcon, Alert, Button, Group, Modal, NumberInput, Select, SimpleGrid, Stack, Switch, Table, Text, TextInput } from '@mantine/core';
import { IconEdit, IconPlus, IconTrash } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { useCrud, useHotelQuery } from '@/api/hooks';
import type { CancellationPolicy, Hotel } from '@/api/types';
import { useAuth, useHotel } from '@/auth/AuthProvider';
import { LocalizedTextInput } from '@/components/LocalizedTextInput';
import { ActiveBadge, confirmDelete, SubmitButton } from '@/components/ui';
import { applyFieldErrors, errorMessage, notifyError, notifySuccess } from '@/lib/errors';
import type { LocalizedText } from '@/lib/localized';
import { policySummary, usePricingLookups } from './shared';

interface Draft {
  id?: string;
  version?: number;
  code: string;
  name: LocalizedText;
  description: LocalizedText;
  refundable: boolean;
  free_until_days: number | string;
  penalty_kind: 'percent' | 'nights';
  penalty_value: number | string;
  no_show_nights: number | string;
  is_active: boolean;
}

export default function PoliciesTab() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const canManage = can('pricing.manage');
  const pricing = usePricingLookups();
  const crud = useCrud<CancellationPolicy>('cancellation_policy', '/cancellation-policies', ['cancellation_policy', 'rate_plan']);
  const [draft, setDraft] = useState<Draft | null>(null);

  const penalty = (p: CancellationPolicy) =>
    p.penalty_kind === 'percent' ? t('pricing.policies.penalty_percent', { value: Number(p.penalty_value) }) : t('pricing.policies.penalty_nights', { count: Number(p.penalty_value) });

  return (
    <Stack>
      <Group justify="space-between">
        <Text size="sm" c="dimmed" maw={680}>
          {t('pricing.policies.hint')}
        </Text>
        {canManage && (
          <Button
            leftSection={<IconPlus size={16} />}
            onClick={() => setDraft({ code: '', name: {}, description: {}, refundable: true, free_until_days: 2, penalty_kind: 'nights', penalty_value: 1, no_show_nights: 1, is_active: true })}
          >
            {t('pricing.policies.add')}
          </Button>
        )}
      </Group>
      <div className="hms-table-wrap">
        <Table miw={640}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t('common.name')}</Table.Th>
              <Table.Th>{t('pricing.policies.free_cancellation')}</Table.Th>
              <Table.Th>{t('pricing.policies.penalty')}</Table.Th>
              <Table.Th>{t('pricing.policies.no_show')}</Table.Th>
              <Table.Th>{t('common.status')}</Table.Th>
              {canManage && <Table.Th w={80} />}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {pricing.policies.map((p) => (
              <Table.Tr key={p.id}>
                <Table.Td>
                  <Text size="sm" fw={600}>
                    {pricing.policyName(p.id)}
                  </Text>
                  <Text size="xs" c="dimmed">
                    {p.code}
                  </Text>
                </Table.Td>
                <Table.Td>{policySummary(p, t)}</Table.Td>
                <Table.Td>{penalty(p)}</Table.Td>
                <Table.Td>{t('pricing.policies.penalty_nights', { count: p.no_show_nights })}</Table.Td>
                <Table.Td>
                  <ActiveBadge active={p.is_active} />
                </Table.Td>
                {canManage && (
                  <Table.Td>
                    <Group gap={4} justify="flex-end" wrap="nowrap">
                      <ActionIcon
                        variant="subtle"
                        aria-label={t('common.edit')}
                        onClick={() => setDraft({ ...p, refundable: p.free_until_days !== null, free_until_days: p.free_until_days ?? 0 })}
                      >
                        <IconEdit size={16} />
                      </ActionIcon>
                      <ActionIcon
                        variant="subtle"
                        color="red"
                        aria-label={t('common.delete')}
                        onClick={() =>
                          confirmDelete({
                            title: t('pricing.policies.delete', { name: pricing.policyName(p.id) }),
                            onConfirm: () => crud.remove.mutateAsync(p.id).then(() => notifySuccess(t('common.deleted')), notifyError),
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
      {draft && <PolicyModal draft={draft} crud={crud} onClose={() => setDraft(null)} />}
    </Stack>
  );
}

function PolicyModal({ draft, crud, onClose }: { draft: Draft; crud: ReturnType<typeof useCrud<CancellationPolicy>>; onClose: () => void }) {
  const { t } = useTranslation();
  const hotel = useHotel();
  const profile = useHotelQuery<Hotel>('hotel', '');
  const [v, setV] = useState(draft);
  const [error, setError] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const languages = profile.data?.supported_languages ?? [hotel.default_language];
  const set = (patch: Partial<Draft>) => setV((x) => ({ ...x, ...patch }));

  const submit = async () => {
    const { id, version, refundable, ...rest } = v;
    const body = {
      ...rest,
      free_until_days: refundable ? Number(rest.free_until_days) : null,
      penalty_value: String(rest.penalty_value),
      no_show_nights: Number(rest.no_show_nights),
    };
    try {
      if (id) await crud.update.mutateAsync({ id, body: { ...body, version } });
      else await crud.create.mutateAsync(body as never);
      notifySuccess(t('common.saved'));
      onClose();
    } catch (err) {
      const map: Record<string, string> = {};
      if (!applyFieldErrors(err, (k, m) => (map[k] = m))) setError(errorMessage(err));
      setErrors(map);
    }
  };

  return (
    <Modal opened onClose={onClose} title={draft.id ? t('pricing.policies.edit') : t('pricing.policies.add')} size="lg">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <Stack>
          {error && <Alert color="red">{error}</Alert>}
          <TextInput label={t('common.code')} required value={v.code} onChange={(e) => set({ code: e.currentTarget.value })} error={errors.code} />
          <LocalizedTextInput label={t('common.name')} required languages={languages} value={v.name} onChange={(x) => set({ name: x })} error={errors.name} />
          <LocalizedTextInput label={t('pricing.policies.guest_text')} description={t('pricing.policies.guest_text_hint')} multiline languages={languages} value={v.description} onChange={(x) => set({ description: x })} />
          <Switch label={t('pricing.policies.allows_free')} checked={v.refundable} onChange={(e) => set({ refundable: e.currentTarget.checked })} />
          {v.refundable && (
            <NumberInput label={t('pricing.policies.free_until_days')} description={t('pricing.policies.free_until_days_hint')} min={0} max={365} value={v.free_until_days} onChange={(x) => set({ free_until_days: x })} />
          )}
          <SimpleGrid cols={2}>
            <Select
              label={t('pricing.policies.penalty')}
              allowDeselect={false}
              data={[
                { value: 'nights', label: t('pricing.policies.penalty_kind_nights') },
                { value: 'percent', label: t('pricing.policies.penalty_kind_percent') },
              ]}
              value={v.penalty_kind}
              onChange={(x) => x && set({ penalty_kind: x as Draft['penalty_kind'] })}
            />
            <NumberInput label={t('pricing.policies.penalty_value')} min={0} max={v.penalty_kind === 'percent' ? 100 : 365} decimalScale={2} value={v.penalty_value} onChange={(x) => set({ penalty_value: x })} />
          </SimpleGrid>
          <NumberInput label={t('pricing.policies.no_show_nights')} min={0} max={365} value={v.no_show_nights} onChange={(x) => set({ no_show_nights: x })} />
          <Text size="xs" c="dimmed">
            {t('pricing.policies.fees_later')}
          </Text>
          <Switch label={t('common.active')} checked={v.is_active} onChange={(e) => set({ is_active: e.currentTarget.checked })} />
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <SubmitButton loading={crud.create.isPending || crud.update.isPending}>{t('common.save')}</SubmitButton>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}
