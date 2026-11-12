import { useMemo, useState } from 'react';
import {
  ActionIcon,
  Badge,
  Button,
  Card,
  Drawer,
  Group,
  Modal,
  MultiSelect,
  NumberInput,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Table,
  Text,
  Textarea,
  TextInput,
} from '@mantine/core';
import { useForm } from '@mantine/form';
import { IconEdit, IconPlus, IconSearch, IconStack2, IconTrash } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { api } from '@/api/client';
import { useCrud, useHotelMutation, useHotelQuery } from '@/api/hooks';
import type { Amenity, BathroomType, BedItem, Building, Floor, Room, RoomType } from '@/api/types';
import { useAuth, useHotel } from '@/auth/AuthProvider';
import { BedConfigurationInput, useBedSummary } from '@/components/BedConfigurationInput';
import { ActiveBadge, confirmDelete, EmptyState, PageHeader, SubmitButton } from '@/components/ui';
import { applyFieldErrors, notifyError, notifySuccess } from '@/lib/errors';
import { formatMoney } from '@/lib/format';
import { pickLocalized } from '@/lib/localized';

const HK_COLORS: Record<Room['housekeeping_status'], string> = {
  clean: 'lagoon',
  inspected: 'teal',
  dirty: 'orange',
  in_progress: 'blue',
};
const BATHROOMS: BathroomType[] = ['private_shower', 'private_bathtub', 'private_shower_bathtub', 'shared'];
const VIEWS = ['sea', 'garden', 'pool', 'city', 'mountain', 'courtyard', 'river'];

interface Draft {
  id?: string;
  version?: number;
  room_type_id: string;
  building_id: string | null;
  floor_id: string | null;
  number: string;
  name: string;
  max_occupancy: number | string;
  override_beds: boolean;
  bed_configuration: BedItem[];
  size_sqm: number | string;
  bathroom: BathroomType | null;
  has_balcony: boolean;
  view: string | null;
  base_price: number | string;
  notes: string;
  sort_order: number;
  is_active: boolean;
  amenity_ids: string[];
}

function useLookups() {
  const types = useHotelQuery<RoomType[]>('room_type', '/room-types');
  const buildings = useHotelQuery<Building[]>('building', '/buildings');
  const floors = useHotelQuery<Floor[]>('floor', '/floors');
  const amenities = useHotelQuery<Amenity[]>('amenity', '/amenities');
  return { types: types.data ?? [], buildings: buildings.data ?? [], floors: floors.data ?? [], amenities: amenities.data ?? [] };
}

export default function RoomsPage() {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const { can } = useAuth();
  const canEdit = can('config.rooms.manage');
  const rooms = useHotelQuery<Room[]>('room', '/rooms');
  const { types, buildings, floors } = useLookups();
  const crud = useCrud<Room>('room', '/rooms', ['room', 'room_type']);
  const [filters, setFilters] = useState({ q: '', type: null as string | null, building: null as string | null, status: 'active' });
  const [draft, setDraft] = useState<Draft | null>(null);
  const [bulkOpen, setBulkOpen] = useState(false);
  const beds = useBedSummary();
  const lang = i18n.language;

  const typeById = useMemo(() => new Map(types.map((x) => [x.id, x])), [types]);
  const floorById = useMemo(() => new Map(floors.map((x) => [x.id, x])), [floors]);
  const buildingById = useMemo(() => new Map(buildings.map((x) => [x.id, x])), [buildings]);

  const visible = (rooms.data ?? []).filter((r) => {
    if (filters.status === 'active' && !r.is_active) return false;
    if (filters.status === 'inactive' && r.is_active) return false;
    if (filters.type && r.room_type_id !== filters.type) return false;
    if (filters.building && r.building_id !== filters.building) return false;
    const q = filters.q.trim().toLowerCase();
    return !q || r.number.toLowerCase().includes(q) || (r.name ?? '').toLowerCase().includes(q);
  });

  const newDraft = (): Draft => ({
    room_type_id: types[0]?.id ?? '',
    building_id: null,
    floor_id: null,
    number: '',
    name: '',
    max_occupancy: '',
    override_beds: false,
    bed_configuration: [],
    size_sqm: '',
    bathroom: null,
    has_balcony: false,
    view: null,
    base_price: '',
    notes: '',
    sort_order: 0,
    is_active: true,
    amenity_ids: [],
  });

  const editDraft = (r: Room): Draft => ({
    ...r,
    name: r.name ?? '',
    max_occupancy: r.max_occupancy ?? '',
    override_beds: r.bed_configuration !== null,
    bed_configuration: r.bed_configuration ?? [],
    size_sqm: r.size_sqm ?? '',
    base_price: r.base_price ?? '',
    notes: r.notes ?? '',
  });

  const total = rooms.data?.filter((r) => r.is_active).length ?? 0;

  return (
    <>
      <PageHeader
        title={t('nav.rooms')}
        description={t('rooms.description', { count: total })}
        actions={
          canEdit && (
            <>
              <Button variant="default" leftSection={<IconStack2 size={16} />} onClick={() => setBulkOpen(true)} disabled={types.length === 0}>
                {t('rooms.bulk_add')}
              </Button>
              <Button leftSection={<IconPlus size={16} />} onClick={() => setDraft(newDraft())} disabled={types.length === 0}>
                {t('rooms.add')}
              </Button>
            </>
          )
        }
      />
      <Card mb="md" padding="md">
        <Group gap="sm" wrap="wrap">
          <TextInput
            placeholder={t('rooms.search')}
            leftSection={<IconSearch size={16} />}
            value={filters.q}
            onChange={(e) => setFilters({ ...filters, q: e.currentTarget.value })}
            w={{ base: '100%', sm: 220 }}
          />
          <Select
            placeholder={t('rooms.all_categories')}
            clearable
            data={types.map((x) => ({ value: x.id, label: pickLocalized(x.name, lang, hotel.default_language) }))}
            value={filters.type}
            onChange={(v) => setFilters({ ...filters, type: v })}
            w={{ base: '100%', sm: 220 }}
          />
          {buildings.length > 1 && (
            <Select
              placeholder={t('rooms.all_buildings')}
              clearable
              data={buildings.map((b) => ({ value: b.id, label: b.name }))}
              value={filters.building}
              onChange={(v) => setFilters({ ...filters, building: v })}
              w={{ base: '100%', sm: 180 }}
            />
          )}
          <Select
            data={[
              { value: 'active', label: t('common.active') },
              { value: 'inactive', label: t('common.inactive') },
              { value: 'all', label: t('common.all') },
            ]}
            value={filters.status}
            allowDeselect={false}
            onChange={(v) => setFilters({ ...filters, status: v ?? 'active' })}
            w={{ base: '100%', sm: 150 }}
          />
        </Group>
      </Card>

      {types.length === 0 && rooms.isSuccess ? (
        <EmptyState title={t('rooms.no_categories')} description={t('rooms.no_categories_hint')} />
      ) : visible.length === 0 && rooms.isSuccess ? (
        <EmptyState title={t('rooms.empty')} description={canEdit ? t('rooms.empty_hint') : undefined} />
      ) : (
        <Card padding={0}>
          <div className="hms-table-wrap">
            <Table miw={520}>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t('rooms.number')}</Table.Th>
                  <Table.Th>{t('rooms.category')}</Table.Th>
                  <Table.Th visibleFrom="sm">{t('rooms.location')}</Table.Th>
                  <Table.Th visibleFrom="lg">{t('rooms.beds')}</Table.Th>
                  <Table.Th ta="right" visibleFrom="md">{t('rooms.capacity')}</Table.Th>
                  <Table.Th ta="right">{t('rooms.base_price')}</Table.Th>
                  <Table.Th>{t('rooms.housekeeping')}</Table.Th>
                  <Table.Th>{t('common.status')}</Table.Th>
                  {canEdit && <Table.Th w={80} />}
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {visible.map((r) => {
                  const type = typeById.get(r.room_type_id);
                  const floor = r.floor_id ? floorById.get(r.floor_id) : undefined;
                  const building = r.building_id ? buildingById.get(r.building_id) : undefined;
                  return (
                    <Table.Tr key={r.id} style={{ opacity: r.is_active ? 1 : 0.6 }}>
                      <Table.Td>
                        <Text fw={650} className="hms-num">
                          {r.number}
                        </Text>
                        {r.name && (
                          <Text size="xs" c="dimmed">
                            {r.name}
                          </Text>
                        )}
                      </Table.Td>
                      <Table.Td>
                        <Group gap={6} wrap="nowrap">
                          {type?.color && <span style={{ width: 8, height: 8, borderRadius: 2, background: type.color }} />}
                          <Text size="sm">{type ? pickLocalized(type.name, lang, hotel.default_language) : '—'}</Text>
                        </Group>
                      </Table.Td>
                      <Table.Td visibleFrom="sm">
                        <Text size="sm">{[building?.name, floor?.name].filter(Boolean).join(' · ') || '—'}</Text>
                      </Table.Td>
                      <Table.Td visibleFrom="lg">
                        <Text size="sm">{beds(r.bed_configuration ?? type?.bed_configuration)}</Text>
                      </Table.Td>
                      <Table.Td ta="right" className="hms-num" visibleFrom="md">
                        {r.max_occupancy ?? type?.max_occupancy ?? '—'}
                      </Table.Td>
                      <Table.Td ta="right" className="hms-num">
                        {formatMoney(r.base_price ?? type?.base_price, hotel.currency_code, lang)}
                      </Table.Td>
                      <Table.Td style={{ whiteSpace: 'nowrap' }}>
                        <Badge variant="light" color={HK_COLORS[r.housekeeping_status]} radius="sm">
                          {t(`rooms.hk.${r.housekeeping_status}`)}
                        </Badge>
                      </Table.Td>
                      <Table.Td>
                        <ActiveBadge active={r.is_active} />
                      </Table.Td>
                      {canEdit && (
                        <Table.Td>
                          <Group gap={4} justify="flex-end" wrap="nowrap">
                            <ActionIcon variant="subtle" aria-label={t('common.edit')} onClick={() => setDraft(editDraft(r))}>
                              <IconEdit size={16} />
                            </ActionIcon>
                            <ActionIcon
                              variant="subtle"
                              color="red"
                              aria-label={t('common.delete')}
                              onClick={() =>
                                confirmDelete({
                                  title: t('rooms.delete', { number: r.number }),
                                  message: t('rooms.delete_hint'),
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
                  );
                })}
              </Table.Tbody>
            </Table>
          </div>
        </Card>
      )}
      {draft && <RoomDrawer draft={draft} crud={crud} onClose={() => setDraft(null)} />}
      {bulkOpen && <BulkModal onClose={() => setBulkOpen(false)} />}
    </>
  );
}

function LocationFields({ form }: { form: { getValues: () => { building_id: string | null; floor_id: string | null }; setFieldValue: (k: never, v: never) => void } }) {
  const { t } = useTranslation();
  const { buildings, floors } = useLookups();
  const v = form.getValues();
  const set = (k: string, val: string | null) => form.setFieldValue(k as never, val as never);
  return (
    <SimpleGrid cols={{ base: 1, sm: 2 }}>
      <Select
        label={t('rooms.building')}
        clearable
        data={buildings.map((b) => ({ value: b.id, label: b.name }))}
        value={v.building_id}
        onChange={(val) => {
          set('building_id', val);
          set('floor_id', null);
        }}
      />
      <Select
        label={t('rooms.floor')}
        clearable
        disabled={!v.building_id}
        data={floors.filter((f) => f.building_id === v.building_id).map((f) => ({ value: f.id, label: f.name }))}
        value={v.floor_id}
        onChange={(val) => set('floor_id', val)}
      />
    </SimpleGrid>
  );
}

function RoomDrawer({ draft, crud, onClose }: { draft: Draft; crud: ReturnType<typeof useCrud<Room>>; onClose: () => void }) {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const { types, amenities } = useLookups();
  const form = useForm<Draft>({ initialValues: draft });
  const v = form.getValues();
  const type = types.find((x) => x.id === v.room_type_id);

  const submit = form.onSubmit(async ({ id, version, override_beds, ...values }) => {
    const body = {
      ...values,
      name: values.name || null,
      max_occupancy: values.max_occupancy === '' ? null : Number(values.max_occupancy),
      bed_configuration: override_beds ? values.bed_configuration : null,
      size_sqm: values.size_sqm === '' ? null : String(values.size_sqm),
      base_price: values.base_price === '' ? null : String(values.base_price),
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

  return (
    <Drawer opened onClose={onClose} title={draft.id ? t('rooms.edit', { number: draft.number }) : t('rooms.add')} size="lg">
      <form onSubmit={submit}>
        <Stack>
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <TextInput label={t('rooms.number')} required {...form.getInputProps('number')} />
            <TextInput label={t('rooms.name')} description={t('rooms.name_hint')} {...form.getInputProps('name')} />
          </SimpleGrid>
          <Select
            label={t('rooms.category')}
            required
            allowDeselect={false}
            data={types.map((x) => ({ value: x.id, label: pickLocalized(x.name, i18n.language, hotel.default_language) }))}
            {...form.getInputProps('room_type_id')}
          />
          <LocationFields form={form as never} />
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <NumberInput
              label={t('rooms.max_occupancy')}
              description={type ? t('rooms.inherits', { value: type.max_occupancy }) : undefined}
              min={1}
              max={50}
              {...form.getInputProps('max_occupancy')}
            />
            <NumberInput
              label={t('rooms.base_price')}
              description={type ? t('rooms.inherits', { value: formatMoney(type.base_price, hotel.currency_code, i18n.language) }) : undefined}
              min={0}
              decimalScale={2}
              {...form.getInputProps('base_price')}
            />
            <NumberInput label={t('rooms.size_sqm')} min={0} decimalScale={2} {...form.getInputProps('size_sqm')} />
            <Select
              label={t('rooms.bathroom')}
              clearable
              data={BATHROOMS.map((b) => ({ value: b, label: t(`rooms.bathrooms.${b}`) }))}
              {...form.getInputProps('bathroom')}
            />
            <Select
              label={t('rooms.view')}
              clearable
              data={VIEWS.map((x) => ({ value: x, label: t(`rooms.views.${x}`) }))}
              {...form.getInputProps('view')}
            />
            <Switch mt={28} label={t('rooms.balcony')} {...form.getInputProps('has_balcony', { type: 'checkbox' })} />
          </SimpleGrid>
          <Switch label={t('rooms.override_beds')} {...form.getInputProps('override_beds', { type: 'checkbox' })} />
          {v.override_beds && <BedConfigurationInput value={v.bed_configuration} onChange={(x) => form.setFieldValue('bed_configuration', x)} />}
          <MultiSelect
            label={t('rooms.extra_amenities')}
            description={t('rooms.extra_amenities_hint')}
            searchable
            data={amenities.filter((a) => a.is_active || v.amenity_ids.includes(a.id)).map((a) => ({ value: a.id, label: pickLocalized(a.name, i18n.language, hotel.default_language) }))}
            {...form.getInputProps('amenity_ids')}
          />
          <Textarea label={t('rooms.notes')} description={t('rooms.notes_hint')} autosize minRows={2} {...form.getInputProps('notes')} />
          <Switch label={t('rooms.active_hint')} {...form.getInputProps('is_active', { type: 'checkbox' })} />
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

function BulkModal({ onClose }: { onClose: () => void }) {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const { types } = useLookups();
  const bulk = useHotelMutation<Record<string, unknown>, Room[]>((h, body) => api.post<Room[]>(h('/rooms/bulk'), body), ['room', 'room_type']);
  const form = useForm({
    initialValues: { room_type_id: types[0]?.id ?? '', building_id: null as string | null, floor_id: null as string | null, prefix: '', start: 101, end: 110, pad: 0 },
  });
  const v = form.getValues();
  const count = Math.max(0, Number(v.end) - Number(v.start) + 1);
  const sample = (n: number) => `${v.prefix}${String(n).padStart(Number(v.pad) || 0, '0')}`;

  const submit = form.onSubmit(async (values) => {
    try {
      const created = await bulk.mutateAsync(values);
      notifySuccess(t('rooms.bulk_created', { count: created.length }));
      onClose();
    } catch (err) {
      if (!applyFieldErrors(err, form.setFieldError)) notifyError(err);
    }
  });

  return (
    <Modal opened onClose={onClose} title={t('rooms.bulk_add')} size="lg">
      <form onSubmit={submit}>
        <Stack>
          <Text size="sm" c="dimmed">
            {t('rooms.bulk_hint')}
          </Text>
          <Select
            label={t('rooms.category')}
            required
            allowDeselect={false}
            data={types.map((x) => ({ value: x.id, label: pickLocalized(x.name, i18n.language, hotel.default_language) }))}
            {...form.getInputProps('room_type_id')}
          />
          <LocationFields form={form as never} />
          <SimpleGrid cols={{ base: 2, sm: 4 }}>
            <TextInput label={t('rooms.prefix')} {...form.getInputProps('prefix')} />
            <NumberInput label={t('rooms.from')} min={0} {...form.getInputProps('start')} />
            <NumberInput label={t('rooms.to')} min={0} {...form.getInputProps('end')} />
            <NumberInput label={t('rooms.digits')} min={0} max={6} {...form.getInputProps('pad')} />
          </SimpleGrid>
          <Text size="sm">
            {count === 1
              ? t('rooms.bulk_preview_single', { first: sample(Number(v.start)) })
              : count > 0 && count <= 500
              ? t('rooms.bulk_preview', { count, first: sample(Number(v.start)), last: sample(Number(v.end)) })
              : t('rooms.bulk_invalid')}
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <SubmitButton loading={bulk.isPending} disabled={count < 1 || count > 500}>
              {t('rooms.bulk_create', { count })}
            </SubmitButton>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}
