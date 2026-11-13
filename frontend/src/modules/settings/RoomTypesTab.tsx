import { useState } from 'react';
import {
  ActionIcon,
  Badge,
  Button,
  ColorInput,
  Divider,
  Drawer,
  Group,
  Menu,
  MultiSelect,
  NumberInput,
  SimpleGrid,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
} from '@mantine/core';
import { useForm } from '@mantine/form';
import { IconChevronDown, IconEdit, IconPlus, IconTrash } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { useCrud, useHotelQuery } from '@/api/hooks';
import type { Amenity, BedItem, Hotel, RoomType } from '@/api/types';
import { useAuth, useHotel } from '@/auth/AuthProvider';
import { BedConfigurationInput, useBedSummary } from '@/components/BedConfigurationInput';
import { LocalizedTextInput } from '@/components/LocalizedTextInput';
import { MediaGallery } from '@/components/MediaGallery';
import { ActiveBadge, confirmDelete, EmptyState, SubmitButton } from '@/components/ui';
import i18n from '@/i18n';
import { applyFieldErrors, notifyError, notifySuccess } from '@/lib/errors';
import { formatMoney } from '@/lib/format';
import { type LocalizedText, pickLocalized } from '@/lib/localized';

interface Draft {
  id?: string;
  version?: number;
  code: string;
  name: LocalizedText;
  description: LocalizedText;
  base_occupancy: number;
  max_occupancy: number;
  max_adults: number;
  max_children: number;
  bed_configuration: BedItem[];
  size_sqm: number | string;
  base_price: number | string;
  extra_adult_price: number | string;
  extra_child_price: number | string;
  color: string;
  sort_order: number;
  is_active: boolean;
  amenity_ids: string[];
}

// Starting points for common categories. Names come from the translation
// files, so a template creates the category in every language at once.
const TEMPLATES: { key: string; code: string; base: number; max: number; adults: number; children: number; beds: BedItem[] }[] = [
  { key: 'standard_single', code: 'STD-SGL', base: 1, max: 1, adults: 1, children: 0, beds: [{ type: 'single', count: 1 }] },
  { key: 'standard_double', code: 'STD-DBL', base: 2, max: 2, adults: 2, children: 0, beds: [{ type: 'double', count: 1 }] },
  { key: 'superior_double', code: 'SUP-DBL', base: 2, max: 3, adults: 2, children: 1, beds: [{ type: 'queen', count: 1 }] },
  { key: 'deluxe', code: 'DLX', base: 2, max: 3, adults: 2, children: 1, beds: [{ type: 'king', count: 1 }] },
  { key: 'twin', code: 'TWN', base: 2, max: 2, adults: 2, children: 0, beds: [{ type: 'single', count: 2 }] },
  { key: 'family', code: 'FAM', base: 4, max: 5, adults: 4, children: 3, beds: [{ type: 'double', count: 1 }, { type: 'single', count: 2 }] },
  { key: 'triple', code: 'TRP', base: 3, max: 3, adults: 3, children: 1, beds: [{ type: 'single', count: 3 }] },
  { key: 'junior_suite', code: 'JS', base: 2, max: 3, adults: 2, children: 1, beds: [{ type: 'king', count: 1 }, { type: 'sofa_bed', count: 1 }] },
  { key: 'executive_suite', code: 'ES', base: 2, max: 4, adults: 3, children: 2, beds: [{ type: 'king', count: 1 }, { type: 'sofa_bed', count: 1 }] },
  { key: 'bungalow', code: 'BNG', base: 2, max: 4, adults: 3, children: 2, beds: [{ type: 'king', count: 1 }] },
  { key: 'apartment', code: 'APT', base: 2, max: 4, adults: 4, children: 2, beds: [{ type: 'double', count: 1 }, { type: 'sofa_bed', count: 1 }] },
  { key: 'dormitory', code: 'DORM', base: 1, max: 8, adults: 8, children: 0, beds: [{ type: 'bunk', count: 4 }] },
];

function templateName(key: string, languages: string[]): LocalizedText {
  return Object.fromEntries(languages.map((lng) => [lng, i18n.t(`settings.room_types.templates.${key}`, { lng })]));
}

const EMPTY: Draft = {
  code: '',
  name: {},
  description: {},
  base_occupancy: 2,
  max_occupancy: 2,
  max_adults: 2,
  max_children: 0,
  bed_configuration: [],
  size_sqm: '',
  base_price: '',
  extra_adult_price: 0,
  extra_child_price: 0,
  color: '',
  sort_order: 0,
  is_active: true,
  amenity_ids: [],
};

export default function RoomTypesTab() {
  const { t, i18n: inst } = useTranslation();
  const hotel = useHotel();
  const { can } = useAuth();
  const canEdit = can('config.rooms.manage');
  const list = useHotelQuery<RoomType[]>('room_type', '/room-types');
  const profile = useHotelQuery<Hotel>('hotel', '');
  const crud = useCrud<RoomType>('room_type', '/room-types', ['room_type', 'room']);
  const [draft, setDraft] = useState<Draft | null>(null);
  const beds = useBedSummary();
  const lang = inst.language;
  const languages = profile.data?.supported_languages ?? [hotel.default_language];

  const fromTemplate = (tpl: (typeof TEMPLATES)[number]) =>
    setDraft({
      ...EMPTY,
      code: tpl.code,
      name: templateName(tpl.key, languages),
      base_occupancy: tpl.base,
      max_occupancy: tpl.max,
      max_adults: tpl.adults,
      max_children: tpl.children,
      bed_configuration: tpl.beds,
    });

  return (
    <Stack>
      <Group justify="space-between">
        <Text c="dimmed" size="sm" maw={640}>
          {t('settings.room_types.hint')}
        </Text>
        {canEdit && (
          <Group gap="xs">
            <Menu position="bottom-end">
              <Menu.Target>
                <Button variant="default" rightSection={<IconChevronDown size={14} />}>
                  {t('settings.room_types.from_template')}
                </Button>
              </Menu.Target>
              <Menu.Dropdown>
                {TEMPLATES.map((tpl) => (
                  <Menu.Item key={tpl.key} onClick={() => fromTemplate(tpl)}>
                    {t(`settings.room_types.templates.${tpl.key}`)}
                  </Menu.Item>
                ))}
              </Menu.Dropdown>
            </Menu>
            <Button leftSection={<IconPlus size={16} />} onClick={() => setDraft({ ...EMPTY })}>
              {t('settings.room_types.add')}
            </Button>
          </Group>
        )}
      </Group>

      {list.data?.length === 0 ? (
        <EmptyState title={t('settings.room_types.empty')} description={t('settings.room_types.empty_hint')} />
      ) : (
        <div className="hms-table-wrap">
          <Table miw={760}>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t('common.name')}</Table.Th>
                <Table.Th>{t('settings.room_types.occupancy')}</Table.Th>
                <Table.Th>{t('rooms.beds')}</Table.Th>
                <Table.Th ta="right">{t('settings.room_types.base_price')}</Table.Th>
                <Table.Th ta="right">{t('settings.room_types.rooms')}</Table.Th>
                <Table.Th>{t('common.status')}</Table.Th>
                {canEdit && <Table.Th w={80} />}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {list.data?.map((rt) => (
                <Table.Tr key={rt.id}>
                  <Table.Td>
                    <Group gap="xs" wrap="nowrap">
                      {rt.color && <span style={{ width: 10, height: 10, borderRadius: 3, background: rt.color, flex: 'none' }} />}
                      <div>
                        <Text fw={600} size="sm">
                          {pickLocalized(rt.name, lang, hotel.default_language)}
                        </Text>
                        <Text size="xs" c="dimmed">
                          {rt.code}
                        </Text>
                      </div>
                    </Group>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">{t('settings.room_types.occupancy_value', { base: rt.base_occupancy, max: rt.max_occupancy })}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">{beds(rt.bed_configuration)}</Text>
                  </Table.Td>
                  <Table.Td ta="right" className="hms-num">
                    {formatMoney(rt.base_price, hotel.currency_code, lang)}
                  </Table.Td>
                  <Table.Td ta="right" className="hms-num">
                    <Badge variant="light" color="gray" radius="sm">
                      {rt.room_count}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    <ActiveBadge active={rt.is_active} />
                  </Table.Td>
                  {canEdit && (
                    <Table.Td>
                      <Group gap={4} justify="flex-end" wrap="nowrap">
                        <ActionIcon
                          variant="subtle"
                          aria-label={t('common.edit')}
                          onClick={() =>
                            setDraft({
                              ...rt,
                              size_sqm: rt.size_sqm ?? '',
                              color: rt.color ?? '',
                            })
                          }
                        >
                          <IconEdit size={16} />
                        </ActionIcon>
                        <ActionIcon
                          variant="subtle"
                          color="red"
                          aria-label={t('common.delete')}
                          onClick={() =>
                            confirmDelete({
                              title: t('settings.room_types.delete', { name: pickLocalized(rt.name, lang) }),
                              onConfirm: () => crud.remove.mutateAsync(rt.id).then(() => notifySuccess(t('common.deleted')), notifyError),
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
      {draft && <RoomTypeDrawer draft={draft} languages={languages} crud={crud} onClose={() => setDraft(null)} />}
    </Stack>
  );
}

function RoomTypeDrawer({ draft, languages, crud, onClose }: { draft: Draft; languages: string[]; crud: ReturnType<typeof useCrud<RoomType>>; onClose: () => void }) {
  const { t, i18n: inst } = useTranslation();
  const hotel = useHotel();
  const { can } = useAuth();
  const amenities = useHotelQuery<Amenity[]>('amenity', '/amenities');
  const form = useForm<Draft>({ initialValues: draft });
  const v = form.getValues();

  const submit = form.onSubmit(async ({ id, version, ...values }) => {
    const body = {
      ...values,
      size_sqm: values.size_sqm === '' ? null : String(values.size_sqm),
      base_price: String(values.base_price),
      extra_adult_price: String(values.extra_adult_price || 0),
      extra_child_price: String(values.extra_child_price || 0),
      color: values.color || null,
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
    <Drawer opened onClose={onClose} title={draft.id ? t('settings.room_types.edit') : t('settings.room_types.add')} size="xl">
      <form onSubmit={submit}>
        <Stack>
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <TextInput label={t('common.code')} description={t('common.code_hint')} required {...form.getInputProps('code')} />
            <ColorInput label={t('settings.room_types.color')} format="hex" swatches={['#1d7a74', '#3b5bdb', '#9c36b5', '#e8590c', '#2f9e44', '#c2255c', '#495057']} {...form.getInputProps('color')} />
          </SimpleGrid>
          <LocalizedTextInput label={t('common.name')} required languages={languages} value={v.name} onChange={(x) => form.setFieldValue('name', x)} error={form.errors.name as string} />
          <LocalizedTextInput label={t('common.description')} multiline languages={languages} value={v.description} onChange={(x) => form.setFieldValue('description', x)} />
          <SimpleGrid cols={{ base: 2, sm: 4 }}>
            <NumberInput label={t('settings.room_types.base_occupancy')} min={1} max={50} required {...form.getInputProps('base_occupancy')} />
            <NumberInput label={t('settings.room_types.max_occupancy')} min={1} max={50} required {...form.getInputProps('max_occupancy')} />
            <NumberInput label={t('settings.room_types.max_adults')} min={1} max={50} required {...form.getInputProps('max_adults')} />
            <NumberInput label={t('settings.room_types.max_children')} min={0} max={50} required {...form.getInputProps('max_children')} />
          </SimpleGrid>
          <BedConfigurationInput value={v.bed_configuration} onChange={(x) => form.setFieldValue('bed_configuration', x)} />
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <NumberInput label={t('settings.room_types.base_price')} description={hotel.currency_code} min={0} decimalScale={2} fixedDecimalScale required {...form.getInputProps('base_price')} />
            <NumberInput label={t('rooms.size_sqm')} min={0} decimalScale={2} {...form.getInputProps('size_sqm')} />
            <NumberInput label={t('settings.room_types.extra_adult_price')} description={t('settings.room_types.per_night')} min={0} decimalScale={2} {...form.getInputProps('extra_adult_price')} />
            <NumberInput label={t('settings.room_types.extra_child_price')} description={t('settings.room_types.per_night')} min={0} decimalScale={2} {...form.getInputProps('extra_child_price')} />
          </SimpleGrid>
          <MultiSelect
            label={t('nav.amenities')}
            searchable
            data={(amenities.data ?? []).filter((a) => a.is_active || v.amenity_ids.includes(a.id)).map((a) => ({ value: a.id, label: pickLocalized(a.name, inst.language, hotel.default_language) }))}
            {...form.getInputProps('amenity_ids')}
          />
          <SimpleGrid cols={2}>
            <NumberInput label={t('common.sort_order')} min={0} {...form.getInputProps('sort_order')} />
            <Switch mt={28} label={t('settings.room_types.active_hint')} {...form.getInputProps('is_active', { type: 'checkbox' })} />
          </SimpleGrid>
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
        <MediaGallery ownerType="room_type" ownerId={draft.id} canEdit={can('config.rooms.manage')} limit={20} />
      ) : (
        <Text size="sm" c="dimmed">
          {t('media.save_first')}
        </Text>
      )}
    </Drawer>
  );
}
