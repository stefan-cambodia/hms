import { useState } from 'react';
import { ActionIcon, Alert, Button, Group, Modal, NumberInput, Select, Stack, Switch, Table, Text } from '@mantine/core';
import { IconEdit, IconPlus, IconTrash } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { useCrud, useHotelQuery } from '@/api/hooks';
import type { Currency } from '@/api/types';
import { useAuth, useHotel } from '@/auth/AuthProvider';
import { ActiveBadge, confirmDelete, EmptyState, SubmitButton } from '@/components/ui';
import { applyFieldErrors, errorMessage, notifyError, notifySuccess } from '@/lib/errors';
import { formatDateTime, formatMoney, formatNumber } from '@/lib/format';
import { CURRENCY_CODES } from '@/lib/refdata';

interface Draft {
  id?: string;
  version?: number;
  code: string;
  units_per_base: number | string;
  is_active: boolean;
}

/** Foreign currencies accepted for payments, with their exchange rate. */
export default function CurrenciesTab() {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const { can } = useAuth();
  const canEdit = can('config.currencies.manage');
  const list = useHotelQuery<Currency[]>('currency', '/currencies');
  const crud = useCrud<Currency>('currency', '/currencies');
  const [draft, setDraft] = useState<Draft | null>(null);

  return (
    <Stack>
      <Group justify="space-between">
        <Text c="dimmed" size="sm" maw={680}>
          {t('settings.currencies.hint', { base: hotel.currency_code })}
        </Text>
        {canEdit && (
          <Button leftSection={<IconPlus size={16} />} onClick={() => setDraft({ code: '', units_per_base: '', is_active: true })}>
            {t('settings.currencies.add')}
          </Button>
        )}
      </Group>
      {list.data?.length === 0 ? (
        <EmptyState title={t('settings.currencies.empty')} description={t('settings.currencies.empty_hint', { base: hotel.currency_code })} />
      ) : (
        <div className="hms-table-wrap">
          <Table miw={560}>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t('settings.currencies.code')}</Table.Th>
                <Table.Th>{t('settings.currencies.rate')}</Table.Th>
                <Table.Th visibleFrom="sm">{t('settings.currencies.updated')}</Table.Th>
                <Table.Th>{t('common.status')}</Table.Th>
                {canEdit && <Table.Th w={80} />}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {list.data?.map((c) => (
                <Table.Tr key={c.id} data-currency={c.code}>
                  <Table.Td fw={600}>{c.code}</Table.Td>
                  <Table.Td className="hms-num">
                    {formatMoney(1, hotel.currency_code, i18n.language)} = {formatNumber(c.units_per_base, i18n.language, 6)} {c.code}
                  </Table.Td>
                  <Table.Td visibleFrom="sm">{formatDateTime(c.updated_at, i18n.language, hotel.timezone)}</Table.Td>
                  <Table.Td>
                    <ActiveBadge active={c.is_active} />
                  </Table.Td>
                  {canEdit && (
                    <Table.Td>
                      <Group gap={4} justify="flex-end" wrap="nowrap">
                        <ActionIcon variant="subtle" aria-label={t('common.edit')} onClick={() => setDraft({ ...c, units_per_base: Number(c.units_per_base) })}>
                          <IconEdit size={16} />
                        </ActionIcon>
                        <ActionIcon
                          variant="subtle"
                          color="red"
                          aria-label={t('common.delete')}
                          onClick={() =>
                            confirmDelete({
                              title: t('settings.currencies.delete', { code: c.code }),
                              message: t('settings.currencies.delete_body'),
                              onConfirm: () => crud.remove.mutateAsync(c.id).then(() => notifySuccess(t('common.deleted')), notifyError),
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
      {draft && <CurrencyModal draft={draft} crud={crud} onClose={() => setDraft(null)} />}
    </Stack>
  );
}

function CurrencyModal({ draft, crud, onClose }: { draft: Draft; crud: ReturnType<typeof useCrud<Currency>>; onClose: () => void }) {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const [v, setV] = useState(draft);
  const [error, setError] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const submit = async () => {
    try {
      if (v.id) await crud.update.mutateAsync({ id: v.id, body: { version: v.version, units_per_base: String(v.units_per_base), is_active: v.is_active } });
      else await crud.create.mutateAsync({ code: v.code, units_per_base: String(v.units_per_base), is_active: v.is_active } as never);
      notifySuccess(t('common.saved'));
      onClose();
    } catch (err) {
      const map: Record<string, string> = {};
      if (!applyFieldErrors(err, (k, m) => (map[k] = m))) setError(errorMessage(err));
      setErrors(map);
    }
  };
  return (
    <Modal opened onClose={onClose} title={v.id ? t('settings.currencies.edit', { code: v.code }) : t('settings.currencies.add')}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <Stack>
          {error && <Alert color="red">{error}</Alert>}
          <Select
            label={t('settings.currencies.code')}
            searchable
            required
            disabled={!!v.id}
            data={CURRENCY_CODES.filter((c) => c !== hotel.currency_code)}
            value={v.code || null}
            onChange={(x) => setV({ ...v, code: x ?? '' })}
            error={errors.code}
          />
          <NumberInput
            label={t('settings.currencies.rate_label', { base: hotel.currency_code, code: v.code || '…' })}
            description={t('settings.currencies.rate_hint')}
            required
            min={0.000001}
            decimalScale={6}
            thousandSeparator=","
            value={v.units_per_base}
            onChange={(x) => setV({ ...v, units_per_base: x })}
            error={errors.units_per_base}
          />
          {v.code && Number(v.units_per_base) > 0 && (
            <Text size="sm" c="dimmed">
              {t('settings.currencies.example', {
                amount: formatMoney(100, hotel.currency_code, i18n.language),
                converted: formatNumber(100 * Number(v.units_per_base), i18n.language, 2),
                code: v.code,
              })}
            </Text>
          )}
          <Switch label={t('settings.currencies.accepted')} checked={v.is_active} onChange={(e) => setV({ ...v, is_active: e.currentTarget.checked })} />
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <SubmitButton loading={crud.create.isPending || crud.update.isPending} disabled={!v.code || !(Number(v.units_per_base) > 0)}>
              {t('common.save')}
            </SubmitButton>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}
