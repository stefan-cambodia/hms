import { useState } from 'react';
import { ActionIcon, Alert, Badge, Button, Card, Group, Modal, NumberInput, Select, SimpleGrid, Stack, Table, Text, Textarea, TextInput } from '@mantine/core';
import { IconEdit, IconPlus, IconTrash } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { useCrud, useHotelQuery } from '@/api/hooks';
import type { Vehicle, VehicleKind } from '@/api/types';
import { useAuth, useHotel } from '@/auth/AuthProvider';
import { confirmDelete, EmptyState, SubmitButton } from '@/components/ui';
import { applyFieldErrors, errorMessage, notifyError, notifySuccess } from '@/lib/errors';
import { formatDate, formatMoney } from '@/lib/format';
import { KINDS } from './shared';

type Draft = Omit<Vehicle, 'id' | 'version' | 'available' | 'unavailable_reason' | 'document_warning' | 'daily_rate' | 'hourly_rate' | 'driver_daily_rate' | 'deposit_amount'> & {
  id?: string;
  version?: number;
  daily_rate: number | string;
  hourly_rate: number | string;
  driver_daily_rate: number | string;
  deposit_amount: number | string;
};

const EMPTY: Draft = {
  code: '',
  plate: '',
  kind: 'scooter',
  make: '',
  model: '',
  color: '',
  year: null,
  seats: 2,
  transmission: null,
  daily_rate: '',
  hourly_rate: '',
  driver_daily_rate: '',
  deposit_amount: 0,
  odometer: 0,
  status: 'available',
  insurance_expiry: null,
  registration_expiry: null,
  notes: '',
  sort_order: 0,
};

export default function FleetTab() {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const { can } = useAuth();
  const manage = can('vehicles.manage');
  const fleet = useHotelQuery<Vehicle[]>('vehicle', '/vehicles');
  const crud = useCrud<Vehicle>('vehicle', '/vehicles', ['vehicle', 'vehicle_rental']);
  const [draft, setDraft] = useState<Draft | null>(null);
  const money = (v: string | null) => (v === null ? '—' : formatMoney(v, hotel.currency_code, i18n.language));
  return (
    <Stack>
      <Group justify="space-between">
        <Text size="sm" c="dimmed" maw={680}>
          {t('vehicles.fleet_hint')}
        </Text>
        {manage && (
          <Button leftSection={<IconPlus size={16} />} onClick={() => setDraft(EMPTY)}>
            {t('vehicles.add_vehicle')}
          </Button>
        )}
      </Group>
      {fleet.data && fleet.data.length === 0 ? (
        <EmptyState title={t('vehicles.no_fleet')} description={manage ? t('vehicles.no_fleet_hint') : undefined} />
      ) : (
        <Card padding={0}>
          <div className="hms-table-wrap">
            <Table verticalSpacing="sm" miw={760}>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t('vehicles.vehicle')}</Table.Th>
                  <Table.Th>{t('vehicles.rates')}</Table.Th>
                  <Table.Th>{t('vehicles.odometer')}</Table.Th>
                  <Table.Th>{t('common.status')}</Table.Th>
                  {manage && <Table.Th w={80} />}
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {fleet.data?.map((v) => (
                  <Table.Tr key={v.id} data-vehicle={v.code}>
                    <Table.Td>
                      <Text size="sm" fw={600}>
                        {v.code} · {t(`vehicles.kinds.${v.kind}`)}
                      </Text>
                      <Text size="xs" c="dimmed">
                        {[v.make, v.model, v.color, v.plate].filter(Boolean).join(' · ') || '—'}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm">
                        {money(v.daily_rate)} / {t('vehicles.day')}
                        {v.hourly_rate ? ` · ${money(v.hourly_rate)} / h` : ''}
                      </Text>
                      <Text size="xs" c="dimmed">
                        {v.driver_daily_rate ? `${t('vehicles.driver')} ${money(v.driver_daily_rate)} · ` : ''}
                        {t('vehicles.deposit')} {money(v.deposit_amount)}
                      </Text>
                    </Table.Td>
                    <Table.Td className="hms-num">{v.odometer} km</Table.Td>
                    <Table.Td>
                      <Group gap={4}>
                        <Badge size="sm" variant="light" color={v.status === 'available' ? 'teal' : v.status === 'maintenance' ? 'orange' : 'gray'}>
                          {t(`vehicles.vehicle_status.${v.status}`)}
                        </Badge>
                        {v.document_warning && (
                          <Badge size="sm" variant={v.document_warning.endsWith('expired') ? 'filled' : 'light'} color="red">
                            {t(`vehicles.document_warnings.${v.document_warning}`, {
                              date: formatDate(v.document_warning.startsWith('insurance') ? v.insurance_expiry : v.registration_expiry, i18n.language),
                            })}
                          </Badge>
                        )}
                      </Group>
                    </Table.Td>
                    {manage && (
                      <Table.Td>
                        <Group gap={4} justify="flex-end" wrap="nowrap">
                          <ActionIcon
                            variant="subtle"
                            aria-label={t('common.edit')}
                            onClick={() =>
                              setDraft({
                                ...v,
                                plate: v.plate ?? '',
                                make: v.make ?? '',
                                model: v.model ?? '',
                                color: v.color ?? '',
                                notes: v.notes ?? '',
                                daily_rate: Number(v.daily_rate),
                                hourly_rate: v.hourly_rate === null ? '' : Number(v.hourly_rate),
                                driver_daily_rate: v.driver_daily_rate === null ? '' : Number(v.driver_daily_rate),
                                deposit_amount: Number(v.deposit_amount),
                              })
                            }
                          >
                            <IconEdit size={16} />
                          </ActionIcon>
                          <ActionIcon
                            variant="subtle"
                            color="red"
                            aria-label={t('common.delete')}
                            onClick={() => confirmDelete({ title: t('vehicles.delete_vehicle', { code: v.code }), onConfirm: () => crud.remove.mutateAsync(v.id).then(() => notifySuccess(t('common.deleted')), notifyError) })}
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
        </Card>
      )}
      {draft && <VehicleModal draft={draft} crud={crud} onClose={() => setDraft(null)} />}
    </Stack>
  );
}

function VehicleModal({ draft, crud, onClose }: { draft: Draft; crud: ReturnType<typeof useCrud<Vehicle>>; onClose: () => void }) {
  const { t } = useTranslation();
  const [v, setV] = useState(draft);
  const [error, setError] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const set = (patch: Partial<Draft>) => setV((x) => ({ ...x, ...patch }));
  const num = (x: number | string) => (x === '' || x === null ? null : String(x));
  const submit = async () => {
    const { id, version, ...rest } = v;
    const body = {
      ...rest,
      plate: rest.plate?.trim() || null,
      make: rest.make?.trim() || null,
      model: rest.model?.trim() || null,
      color: rest.color?.trim() || null,
      notes: rest.notes?.trim() || null,
      daily_rate: String(rest.daily_rate),
      hourly_rate: num(rest.hourly_rate),
      driver_daily_rate: num(rest.driver_daily_rate),
      deposit_amount: String(rest.deposit_amount || 0),
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
    <Modal opened onClose={onClose} title={draft.id ? t('vehicles.edit_vehicle') : t('vehicles.add_vehicle')} size="lg">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <Stack>
          {error && <Alert color="red">{error}</Alert>}
          <SimpleGrid cols={{ base: 1, sm: 3 }}>
            <TextInput label={t('vehicles.code')} required maxLength={20} value={v.code} onChange={(e) => set({ code: e.currentTarget.value })} error={errors.code} />
            <Select label={t('vehicles.kind')} allowDeselect={false} data={KINDS.map((k) => ({ value: k, label: t(`vehicles.kinds.${k}`) }))} value={v.kind} onChange={(x) => x && set({ kind: x as VehicleKind })} />
            <TextInput label={t('vehicles.plate')} maxLength={20} value={v.plate ?? ''} onChange={(e) => set({ plate: e.currentTarget.value })} />
          </SimpleGrid>
          <SimpleGrid cols={{ base: 1, sm: 3 }}>
            <TextInput label={t('vehicles.make')} maxLength={60} value={v.make ?? ''} onChange={(e) => set({ make: e.currentTarget.value })} />
            <TextInput label={t('vehicles.model')} maxLength={60} value={v.model ?? ''} onChange={(e) => set({ model: e.currentTarget.value })} />
            <TextInput label={t('vehicles.color')} maxLength={30} value={v.color ?? ''} onChange={(e) => set({ color: e.currentTarget.value })} />
          </SimpleGrid>
          <SimpleGrid cols={{ base: 2, sm: 4 }}>
            <NumberInput label={t('vehicles.daily_rate')} required min={0} decimalScale={2} value={v.daily_rate} onChange={(x) => set({ daily_rate: x })} />
            <NumberInput label={t('vehicles.hourly_rate')} min={0} decimalScale={2} value={v.hourly_rate} onChange={(x) => set({ hourly_rate: x })} />
            <NumberInput label={t('vehicles.driver_rate')} min={0} decimalScale={2} value={v.driver_daily_rate} onChange={(x) => set({ driver_daily_rate: x })} />
            <NumberInput label={t('vehicles.deposit')} min={0} decimalScale={2} value={v.deposit_amount} onChange={(x) => set({ deposit_amount: x })} />
          </SimpleGrid>
          <SimpleGrid cols={{ base: 2, sm: 4 }}>
            <NumberInput label={t('vehicles.seats')} min={1} max={60} value={v.seats} onChange={(x) => set({ seats: Number(x) || 1 })} />
            <NumberInput label={t('vehicles.odometer')} min={0} value={v.odometer} onChange={(x) => set({ odometer: Number(x) || 0 })} suffix=" km" />
            <TextInput label={t('vehicles.insurance_expiry')} type="date" value={v.insurance_expiry ?? ''} onChange={(e) => set({ insurance_expiry: e.currentTarget.value || null })} />
            <TextInput label={t('vehicles.registration_expiry')} type="date" value={v.registration_expiry ?? ''} onChange={(e) => set({ registration_expiry: e.currentTarget.value || null })} />
          </SimpleGrid>
          <Select
            label={t('common.status')}
            allowDeselect={false}
            data={(['available', 'maintenance', 'retired'] as const).map((s) => ({ value: s, label: t(`vehicles.vehicle_status.${s}`) }))}
            value={v.status}
            onChange={(x) => x && set({ status: x as Draft['status'] })}
          />
          <Textarea label={t('vehicles.notes')} autosize minRows={1} maxLength={2000} value={v.notes ?? ''} onChange={(e) => set({ notes: e.currentTarget.value })} />
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <SubmitButton loading={crud.create.isPending || crud.update.isPending} disabled={!v.code.trim() || v.daily_rate === ''}>
              {t('common.save')}
            </SubmitButton>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}
