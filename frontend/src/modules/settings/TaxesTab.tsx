import { useState } from 'react';
import { ActionIcon, Button, Group, Modal, NumberInput, Select, Stack, Switch, Table, Text, TextInput } from '@mantine/core';
import { useForm } from '@mantine/form';
import { IconEdit, IconPlus, IconTrash } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { useCrud, useHotelQuery } from '@/api/hooks';
import type { Hotel, TaxRate } from '@/api/types';
import { useAuth, useHotel } from '@/auth/AuthProvider';
import { LocalizedTextInput } from '@/components/LocalizedTextInput';
import { ActiveBadge, confirmDelete, EmptyState, SubmitButton } from '@/components/ui';
import { applyFieldErrors, notifyError, notifySuccess } from '@/lib/errors';
import { formatMoney } from '@/lib/format';
import { type LocalizedText, pickLocalized } from '@/lib/localized';

interface Draft {
  id?: string;
  version?: number;
  code: string;
  name: LocalizedText;
  kind: TaxRate['kind'];
  rate: number | string;
  is_inclusive: boolean;
  applies_to: TaxRate['applies_to'];
  sort_order: number;
  is_active: boolean;
}

export default function TaxesTab() {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const { can } = useAuth();
  const canEdit = can('config.taxes.manage');
  const list = useHotelQuery<TaxRate[]>('tax_rate', '/tax-rates');
  const profile = useHotelQuery<Hotel>('hotel', '');
  const crud = useCrud<TaxRate>('tax_rate', '/tax-rates');
  const [draft, setDraft] = useState<Draft | null>(null);
  const languages = profile.data?.supported_languages ?? [hotel.default_language];

  const rateLabel = (tax: TaxRate) =>
    tax.kind === 'percent' ? `${Number(tax.rate)} %` : `${formatMoney(tax.rate, hotel.currency_code, i18n.language)} ${t(`settings.taxes.kind_suffix.${tax.kind}`)}`;

  return (
    <Stack>
      <Group justify="space-between">
        <Text c="dimmed" size="sm" maw={640}>
          {t('settings.taxes.hint')}
        </Text>
        {canEdit && (
          <Button
            leftSection={<IconPlus size={16} />}
            onClick={() => setDraft({ code: '', name: {}, kind: 'percent', rate: '', is_inclusive: false, applies_to: 'all', sort_order: 0, is_active: true })}
          >
            {t('settings.taxes.add')}
          </Button>
        )}
      </Group>
      {list.data?.length === 0 ? (
        <EmptyState title={t('settings.taxes.empty')} description={t('settings.taxes.empty_hint')} />
      ) : (
        <div className="hms-table-wrap">
          <Table miw={640}>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t('common.name')}</Table.Th>
                <Table.Th>{t('settings.taxes.rate')}</Table.Th>
                <Table.Th>{t('settings.taxes.applies_to')}</Table.Th>
                <Table.Th>{t('settings.taxes.inclusive')}</Table.Th>
                <Table.Th>{t('common.status')}</Table.Th>
                {canEdit && <Table.Th w={80} />}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {list.data?.map((tax) => (
                <Table.Tr key={tax.id}>
                  <Table.Td>
                    <Text size="sm" fw={600}>
                      {pickLocalized(tax.name, i18n.language, hotel.default_language)}
                    </Text>
                    <Text size="xs" c="dimmed">
                      {tax.code}
                    </Text>
                  </Table.Td>
                  <Table.Td className="hms-num">{rateLabel(tax)}</Table.Td>
                  <Table.Td>{t(`settings.taxes.scope.${tax.applies_to}`)}</Table.Td>
                  <Table.Td>{tax.is_inclusive ? t('settings.taxes.included') : t('settings.taxes.added')}</Table.Td>
                  <Table.Td>
                    <ActiveBadge active={tax.is_active} />
                  </Table.Td>
                  {canEdit && (
                    <Table.Td>
                      <Group gap={4} justify="flex-end" wrap="nowrap">
                        <ActionIcon variant="subtle" aria-label={t('common.edit')} onClick={() => setDraft({ ...tax })}>
                          <IconEdit size={16} />
                        </ActionIcon>
                        <ActionIcon
                          variant="subtle"
                          color="red"
                          aria-label={t('common.delete')}
                          onClick={() =>
                            confirmDelete({
                              title: t('settings.taxes.delete', { name: pickLocalized(tax.name, i18n.language) }),
                              onConfirm: () => crud.remove.mutateAsync(tax.id).then(() => notifySuccess(t('common.deleted')), notifyError),
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
      {draft && <TaxModal draft={draft} languages={languages} crud={crud} onClose={() => setDraft(null)} />}
    </Stack>
  );
}

function TaxModal({ draft, languages, crud, onClose }: { draft: Draft; languages: string[]; crud: ReturnType<typeof useCrud<TaxRate>>; onClose: () => void }) {
  const { t } = useTranslation();
  const form = useForm<Draft>({ initialValues: draft });
  const v = form.getValues();
  const submit = form.onSubmit(async ({ id, version, ...values }) => {
    const body = { ...values, rate: String(values.rate) };
    try {
      if (id) await crud.update.mutateAsync({ id, body: { ...body, version } });
      else await crud.create.mutateAsync(body as never);
      notifySuccess(t('common.saved'));
      onClose();
    } catch (err) {
      if (!applyFieldErrors(err, form.setFieldError)) notifyError(err);
    }
  });
  return (
    <Modal opened onClose={onClose} title={draft.id ? t('settings.taxes.edit') : t('settings.taxes.add')} size="lg">
      <form onSubmit={submit}>
        <Stack>
          <TextInput label={t('common.code')} description={t('common.code_hint')} required {...form.getInputProps('code')} />
          <LocalizedTextInput label={t('common.name')} required languages={languages} value={v.name} onChange={(x) => form.setFieldValue('name', x)} error={form.errors.name as string} />
          <Group grow>
            <Select
              label={t('settings.taxes.kind')}
              allowDeselect={false}
              data={(['percent', 'fixed_per_night', 'fixed_per_person_night'] as const).map((k) => ({ value: k, label: t(`settings.taxes.kinds.${k}`) }))}
              {...form.getInputProps('kind')}
            />
            <NumberInput label={t('settings.taxes.rate')} min={0} max={v.kind === 'percent' ? 100 : undefined} decimalScale={4} required {...form.getInputProps('rate')} />
          </Group>
          <Select
            label={t('settings.taxes.applies_to')}
            allowDeselect={false}
            data={(['all', 'accommodation', 'services', 'food_beverage'] as const).map((k) => ({ value: k, label: t(`settings.taxes.scope.${k}`) }))}
            {...form.getInputProps('applies_to')}
          />
          <Switch label={t('settings.taxes.inclusive_hint')} {...form.getInputProps('is_inclusive', { type: 'checkbox' })} />
          <Group grow>
            <NumberInput label={t('settings.taxes.order')} min={0} {...form.getInputProps('sort_order')} />
            <Switch mt={24} label={t('common.active')} {...form.getInputProps('is_active', { type: 'checkbox' })} />
          </Group>
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
