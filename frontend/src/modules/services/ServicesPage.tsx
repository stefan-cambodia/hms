import { useState } from 'react';
import {
  ActionIcon,
  Badge,
  Button,
  Card,
  Checkbox,
  Divider,
  Drawer,
  Group,
  NumberInput,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Table,
  Tabs,
  Text,
  Textarea,
  TextInput,
} from '@mantine/core';
import { TimeInput } from '@mantine/dates';
import { useForm } from '@mantine/form';
import { IconEdit, IconPlus, IconTrash } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { useCrud, useHotelQuery } from '@/api/hooks';
import type { Facility, Hotel, Service } from '@/api/types';
import { useAuth, useHotel } from '@/auth/AuthProvider';
import { LocalizedTextInput } from '@/components/LocalizedTextInput';
import { MediaGallery } from '@/components/MediaGallery';
import { ActiveBadge, confirmDelete, EmptyState, PageHeader, SubmitButton } from '@/components/ui';
import { applyFieldErrors, notifyError, notifySuccess } from '@/lib/errors';
import { formatMoney } from '@/lib/format';
import { type LocalizedText, pickLocalized } from '@/lib/localized';

export const FACILITY_CATEGORIES = [
  'pool', 'restaurant', 'bar', 'rooftop', 'spa', 'fitness', 'garden', 'parking', 'laundry',
  'transfer', 'room_service', 'meeting_room', 'beach', 'wifi', 'breakfast', 'massage', 'other',
] as const;
const WEEKDAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as const;
const UNITS = ['per_item', 'per_night', 'per_person', 'per_person_night', 'per_stay'] as const;

function useLanguages() {
  const hotel = useHotel();
  const profile = useHotelQuery<Hotel>('hotel', '');
  return profile.data?.supported_languages ?? [hotel.default_language];
}

export default function ServicesPage() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<string | null>('facilities');
  return (
    <>
      <PageHeader title={t('nav.services')} description={t('services.description')} />
      <Tabs value={tab} onChange={setTab} keepMounted={false}>
        <Tabs.List mb="lg">
          <Tabs.Tab value="facilities">{t('services.facilities')}</Tabs.Tab>
          <Tabs.Tab value="services">{t('services.services')}</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="facilities">
          <FacilitiesTab />
        </Tabs.Panel>
        <Tabs.Panel value="services">
          <ServicesTab />
        </Tabs.Panel>
      </Tabs>
    </>
  );
}

// --- Facilities ---------------------------------------------------------------

interface FacilityDraft {
  id?: string;
  version?: number;
  code: string;
  category: string;
  name: LocalizedText;
  description: LocalizedText;
  hours: Record<string, { open: boolean; from: string; to: string }>;
  is_available: boolean;
  pricing_mode: Facility['pricing_mode'];
  price: number | string;
  price_unit: string | null;
  conditions: LocalizedText;
  notes: string;
  sort_order: number;
  is_active: boolean;
}

function hoursToDraft(hours: Facility['opening_hours']): FacilityDraft['hours'] {
  return Object.fromEntries(
    WEEKDAYS.map((d) => {
      const first = hours[d]?.[0];
      return [d, first ? { open: true, from: first[0], to: first[1] } : { open: false, from: '08:00', to: '20:00' }];
    }),
  );
}

function FacilitiesTab() {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const { can } = useAuth();
  const canEdit = can('config.facilities.manage');
  const list = useHotelQuery<Facility[]>('facility', '/facilities');
  const crud = useCrud<Facility>('facility', '/facilities', ['facility', 'service']);
  const [draft, setDraft] = useState<FacilityDraft | null>(null);

  const open = (f?: Facility) =>
    setDraft(
      f
        ? { ...f, hours: hoursToDraft(f.opening_hours), price: f.price ?? '', notes: f.notes ?? '' }
        : {
            code: '', category: 'pool', name: {}, description: {}, hours: hoursToDraft({}), is_available: true,
            pricing_mode: 'free', price: '', price_unit: null, conditions: {}, notes: '', sort_order: 0, is_active: true,
          },
    );

  const hoursSummary = (f: Facility) => {
    const days = WEEKDAYS.filter((d) => f.opening_hours[d]?.length);
    if (!days.length) return t('services.hours_not_set');
    const first = f.opening_hours[days[0]][0];
    const same = days.every((d) => f.opening_hours[d][0][0] === first[0] && f.opening_hours[d][0][1] === first[1]);
    return same && days.length === 7 ? t('services.daily', { from: first[0], to: first[1] }) : days.map((d) => t(`services.days.${d}`)).join(', ');
  };

  return (
    <Stack>
      {canEdit && (
        <Group justify="flex-end">
          <Button leftSection={<IconPlus size={16} />} onClick={() => open()}>
            {t('services.add_facility')}
          </Button>
        </Group>
      )}
      {list.data?.length === 0 ? (
        <EmptyState title={t('services.no_facilities')} description={t('services.no_facilities_hint')} />
      ) : (
        <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }}>
          {list.data?.map((f) => (
            <Card key={f.id} style={{ opacity: f.is_active ? 1 : 0.6 }}>
              <Group justify="space-between" align="flex-start" wrap="nowrap">
                <div>
                  <Text fw={650}>{pickLocalized(f.name, i18n.language, hotel.default_language)}</Text>
                  <Text size="xs" c="dimmed">
                    {t(`services.categories.${f.category}`)}
                  </Text>
                </div>
                {canEdit && (
                  <Group gap={4} wrap="nowrap">
                    <ActionIcon variant="subtle" aria-label={t('common.edit')} onClick={() => open(f)}>
                      <IconEdit size={16} />
                    </ActionIcon>
                    <ActionIcon
                      variant="subtle"
                      color="red"
                      aria-label={t('common.delete')}
                      onClick={() =>
                        confirmDelete({
                          title: t('services.delete_facility', { name: pickLocalized(f.name, i18n.language) }),
                          onConfirm: () => crud.remove.mutateAsync(f.id).then(() => notifySuccess(t('common.deleted')), notifyError),
                        })
                      }
                    >
                      <IconTrash size={16} />
                    </ActionIcon>
                  </Group>
                )}
              </Group>
              <Text size="sm" mt="sm" lineClamp={2} c="dimmed">
                {pickLocalized(f.description, i18n.language, hotel.default_language)}
              </Text>
              <Group gap="xs" mt="md">
                <Badge variant="light" color={f.is_available ? 'lagoon' : 'orange'} radius="sm">
                  {f.is_available ? t('services.available') : t('services.unavailable')}
                </Badge>
                <Badge variant="outline" color="gray" radius="sm">
                  {f.pricing_mode === 'paid' ? formatMoney(f.price, hotel.currency_code, i18n.language) : t(`services.pricing.${f.pricing_mode}`)}
                </Badge>
              </Group>
              <Text size="xs" mt="xs" c="dimmed">
                {hoursSummary(f)}
              </Text>
            </Card>
          ))}
        </SimpleGrid>
      )}
      {draft && <FacilityDrawer draft={draft} crud={crud} onClose={() => setDraft(null)} />}
    </Stack>
  );
}

function FacilityDrawer({ draft, crud, onClose }: { draft: FacilityDraft; crud: ReturnType<typeof useCrud<Facility>>; onClose: () => void }) {
  const { can } = useAuth();
  const { t } = useTranslation();
  const hotel = useHotel();
  const languages = useLanguages();
  const form = useForm<FacilityDraft>({ initialValues: draft });
  const v = form.getValues();

  const submit = form.onSubmit(async ({ id, version, hours, ...values }) => {
    const body = {
      ...values,
      opening_hours: Object.fromEntries(Object.entries(hours).filter(([, h]) => h.open).map(([d, h]) => [d, [[h.from, h.to]]])),
      price: values.price === '' ? null : String(values.price),
      price_unit: values.pricing_mode === 'paid' ? values.price_unit : null,
      notes: values.notes || null,
    };
    try {
      if (id) await crud.update.mutateAsync({ id, body: { ...body, version } });
      else await crud.create.mutateAsync(body as never);
      notifySuccess(t('common.saved'));
      onClose();
    } catch (err) {
      if (!applyFieldErrors(err, form.setFieldError)) notifyError(err);
    }
  });

  const setHours = (day: string, patch: Partial<FacilityDraft['hours'][string]>) => form.setFieldValue('hours', { ...v.hours, [day]: { ...v.hours[day], ...patch } });

  return (
    <Drawer opened onClose={onClose} title={draft.id ? t('services.edit_facility') : t('services.add_facility')} size="xl">
      <form onSubmit={submit}>
        <Stack>
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <TextInput label={t('common.code')} description={t('common.code_hint')} required {...form.getInputProps('code')} />
            <Select
              label={t('services.category')}
              allowDeselect={false}
              searchable
              data={FACILITY_CATEGORIES.map((c) => ({ value: c, label: t(`services.categories.${c}`) }))}
              {...form.getInputProps('category')}
            />
          </SimpleGrid>
          <LocalizedTextInput label={t('common.name')} required languages={languages} value={v.name} onChange={(x) => form.setFieldValue('name', x)} error={form.errors.name as string} />
          <LocalizedTextInput label={t('common.description')} multiline languages={languages} value={v.description} onChange={(x) => form.setFieldValue('description', x)} />
          <div>
            <Text size="sm" fw={500} mb={6}>
              {t('services.opening_hours')}
            </Text>
            <Stack gap={6}>
              {WEEKDAYS.map((d) => (
                <Group key={d} gap="sm" wrap="nowrap">
                  <Checkbox w={130} label={t(`services.days.${d}`)} checked={v.hours[d].open} onChange={(e) => setHours(d, { open: e.currentTarget.checked })} />
                  <TimeInput aria-label={t('services.opens')} value={v.hours[d].from} disabled={!v.hours[d].open} onChange={(e) => setHours(d, { from: e.currentTarget.value })} w={110} />
                  <Text size="sm">–</Text>
                  <TimeInput aria-label={t('services.closes')} value={v.hours[d].to} disabled={!v.hours[d].open} onChange={(e) => setHours(d, { to: e.currentTarget.value })} w={110} />
                </Group>
              ))}
            </Stack>
            {form.errors.opening_hours && (
              <Text c="red" size="xs" mt={4}>
                {form.errors.opening_hours}
              </Text>
            )}
          </div>
          <SimpleGrid cols={{ base: 1, sm: 3 }}>
            <Select
              label={t('services.pricing_mode')}
              allowDeselect={false}
              data={(['free', 'paid', 'on_request'] as const).map((m) => ({ value: m, label: t(`services.pricing.${m}`) }))}
              {...form.getInputProps('pricing_mode')}
            />
            <NumberInput label={t('services.price')} description={hotel.currency_code} min={0} decimalScale={2} disabled={v.pricing_mode !== 'paid'} {...form.getInputProps('price')} />
            <Select
              label={t('services.unit')}
              clearable
              disabled={v.pricing_mode !== 'paid'}
              data={UNITS.map((u) => ({ value: u, label: t(`services.units.${u}`) }))}
              {...form.getInputProps('price_unit')}
            />
          </SimpleGrid>
          <LocalizedTextInput label={t('services.conditions')} multiline languages={languages} value={v.conditions} onChange={(x) => form.setFieldValue('conditions', x)} />
          <Textarea label={t('services.internal_notes')} autosize minRows={2} {...form.getInputProps('notes')} />
          <Group>
            <Switch label={t('services.available_now')} {...form.getInputProps('is_available', { type: 'checkbox' })} />
            <Switch label={t('common.active')} {...form.getInputProps('is_active', { type: 'checkbox' })} />
          </Group>
          <Group justify="flex-end" mt="md">
            <Button variant="default" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <SubmitButton loading={crud.create.isPending || crud.update.isPending}>{t('common.save')}</SubmitButton>
          </Group>
        </Stack>
      </form>
      <Divider my="lg" />
      {draft.id ? (
        <MediaGallery ownerType="facility" ownerId={draft.id} canEdit={can('config.facilities.manage')} limit={20} />
      ) : (
        <Text size="sm" c="dimmed">
          {t('media.save_first')}
        </Text>
      )}
    </Drawer>
  );
}

// --- Sellable services --------------------------------------------------------

interface ServiceDraft {
  id?: string;
  version?: number;
  code: string;
  name: LocalizedText;
  description: LocalizedText;
  facility_id: string | null;
  price: number | string;
  pricing_unit: string;
  sort_order: number;
  is_active: boolean;
}

function ServicesTab() {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const { can } = useAuth();
  const canEdit = can('config.facilities.manage');
  const list = useHotelQuery<Service[]>('service', '/services');
  const facilities = useHotelQuery<Facility[]>('facility', '/facilities');
  const crud = useCrud<Service>('service', '/services');
  const [draft, setDraft] = useState<ServiceDraft | null>(null);
  const languages = useLanguages();

  return (
    <Stack>
      <Group justify="space-between">
        <Text size="sm" c="dimmed" maw={640}>
          {t('services.services_hint')}
        </Text>
        {canEdit && (
          <Button
            leftSection={<IconPlus size={16} />}
            onClick={() => setDraft({ code: '', name: {}, description: {}, facility_id: null, price: '', pricing_unit: 'per_item', sort_order: 0, is_active: true })}
          >
            {t('services.add_service')}
          </Button>
        )}
      </Group>
      {list.data?.length === 0 ? (
        <EmptyState title={t('services.no_services')} />
      ) : (
        <div className="hms-table-wrap">
          <Table miw={600}>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t('common.name')}</Table.Th>
                <Table.Th>{t('services.facility')}</Table.Th>
                <Table.Th ta="right">{t('services.price')}</Table.Th>
                <Table.Th>{t('services.unit')}</Table.Th>
                <Table.Th>{t('common.status')}</Table.Th>
                {canEdit && <Table.Th w={80} />}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {list.data?.map((s) => {
                const facility = facilities.data?.find((f) => f.id === s.facility_id);
                return (
                  <Table.Tr key={s.id}>
                    <Table.Td>
                      <Text size="sm" fw={600}>
                        {pickLocalized(s.name, i18n.language, hotel.default_language)}
                      </Text>
                      <Text size="xs" c="dimmed">
                        {s.code}
                      </Text>
                    </Table.Td>
                    <Table.Td>{facility ? pickLocalized(facility.name, i18n.language, hotel.default_language) : '—'}</Table.Td>
                    <Table.Td ta="right" className="hms-num">
                      {formatMoney(s.price, hotel.currency_code, i18n.language)}
                    </Table.Td>
                    <Table.Td>{t(`services.units.${s.pricing_unit}`)}</Table.Td>
                    <Table.Td>
                      <ActiveBadge active={s.is_active} />
                    </Table.Td>
                    {canEdit && (
                      <Table.Td>
                        <Group gap={4} justify="flex-end" wrap="nowrap">
                          <ActionIcon variant="subtle" aria-label={t('common.edit')} onClick={() => setDraft({ ...s })}>
                            <IconEdit size={16} />
                          </ActionIcon>
                          <ActionIcon
                            variant="subtle"
                            color="red"
                            aria-label={t('common.delete')}
                            onClick={() =>
                              confirmDelete({
                                title: t('services.delete_service', { name: pickLocalized(s.name, i18n.language) }),
                                onConfirm: () => crud.remove.mutateAsync(s.id).then(() => notifySuccess(t('common.deleted')), notifyError),
                              })
                            }
                          >
                            <IconTrash size={16} />
                          </ActionIcon>
                        </Group>
                      </Table.Td>
                    )}
                  </Table.Tr>
                );
              })}
            </Table.Tbody>
          </Table>
        </div>
      )}
      {draft && <ServiceDrawer draft={draft} languages={languages} facilities={facilities.data ?? []} crud={crud} onClose={() => setDraft(null)} />}
    </Stack>
  );
}

function ServiceDrawer({
  draft,
  languages,
  facilities,
  crud,
  onClose,
}: {
  draft: ServiceDraft;
  languages: string[];
  facilities: Facility[];
  crud: ReturnType<typeof useCrud<Service>>;
  onClose: () => void;
}) {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const form = useForm<ServiceDraft>({ initialValues: draft });
  const v = form.getValues();
  const submit = form.onSubmit(async ({ id, version, ...values }) => {
    const body = { ...values, price: String(values.price) };
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
    <Drawer opened onClose={onClose} title={draft.id ? t('services.edit_service') : t('services.add_service')} size="lg">
      <form onSubmit={submit}>
        <Stack>
          <TextInput label={t('common.code')} description={t('common.code_hint')} required {...form.getInputProps('code')} />
          <LocalizedTextInput label={t('common.name')} required languages={languages} value={v.name} onChange={(x) => form.setFieldValue('name', x)} error={form.errors.name as string} />
          <LocalizedTextInput label={t('common.description')} multiline languages={languages} value={v.description} onChange={(x) => form.setFieldValue('description', x)} />
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <NumberInput label={t('services.price')} description={hotel.currency_code} min={0} decimalScale={2} required {...form.getInputProps('price')} />
            <Select
              label={t('services.unit')}
              allowDeselect={false}
              data={UNITS.map((u) => ({ value: u, label: t(`services.units.${u}`) }))}
              {...form.getInputProps('pricing_unit')}
            />
          </SimpleGrid>
          <Select
            label={t('services.facility')}
            description={t('services.facility_hint')}
            clearable
            data={facilities.map((f) => ({ value: f.id, label: pickLocalized(f.name, i18n.language, hotel.default_language) }))}
            {...form.getInputProps('facility_id')}
          />
          <Switch label={t('common.active')} {...form.getInputProps('is_active', { type: 'checkbox' })} />
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
