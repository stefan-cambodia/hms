import { useState } from 'react';
import { ActionIcon, Alert, Badge, Button, Card, Group, Modal, NumberInput, SegmentedControl, Select, SimpleGrid, Stack, Switch, Table, Text, TextInput } from '@mantine/core';
import { IconEdit, IconPlus, IconTrash } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { useCrud, useHotelQuery } from '@/api/hooks';
import type { DiningTable, Facility, Hotel, MenuCategory, MenuItem, Outlet, OutletKind, Station } from '@/api/types';
import { useHotel } from '@/auth/AuthProvider';
import { LocalizedTextInput } from '@/components/LocalizedTextInput';
import { ActiveBadge, confirmDelete, EmptyState, SubmitButton } from '@/components/ui';
import { applyFieldErrors, errorMessage, notifyError, notifySuccess } from '@/lib/errors';
import { formatMoney, formatNumber } from '@/lib/format';
import type { LocalizedText } from '@/lib/localized';
import { useLocalized, useMenu, useOutlet } from './shared';

const KINDS: OutletKind[] = ['restaurant', 'bar', 'cafe', 'room_service', 'other'];
const STATIONS: Station[] = ['kitchen', 'bar', 'none'];

function useLanguages(): string[] {
  const hotel = useHotel();
  const profile = useHotelQuery<Hotel>('hotel', '');
  return profile.data?.supported_languages ?? [hotel.default_language];
}

export default function SetupTab() {
  const { t } = useTranslation();
  const [section, setSection] = useState<'outlets' | 'menu' | 'tables'>('outlets');
  const { outlet, active } = useOutlet();
  return (
    <Stack>
      <SegmentedControl
        value={section}
        onChange={(v) => setSection(v as typeof section)}
        data={(['outlets', 'menu', 'tables'] as const).map((s) => ({ value: s, label: t(`restaurant.setup.${s}`), disabled: s !== 'outlets' && active.length === 0 }))}
        w="fit-content"
      />
      {section === 'outlets' && <OutletsSection />}
      {section === 'menu' && outlet && <MenuSection outlet={outlet} />}
      {section === 'tables' && outlet && <TablesSection outlet={outlet} />}
    </Stack>
  );
}

// --- outlets ------------------------------------------------------------------------------

interface OutletDraft {
  id?: string;
  version?: number;
  code: string;
  name: LocalizedText;
  kind: OutletKind;
  facility_id: string | null;
  service_charge_percent: number | string;
  is_active: boolean;
}

function OutletsSection() {
  const { t, i18n } = useTranslation();
  const loc = useLocalized();
  const { outlets } = useOutlet();
  const crud = useCrud<Outlet>('restaurant_outlet', '/restaurant/outlets', ['restaurant_outlet', 'restaurant_order']);
  const [draft, setDraft] = useState<OutletDraft | null>(null);
  return (
    <Stack>
      <Group justify="space-between">
        <Text size="sm" c="dimmed" maw={640}>
          {t('restaurant.setup.outlets_hint')}
        </Text>
        <Button leftSection={<IconPlus size={16} />} onClick={() => setDraft({ code: '', name: {}, kind: 'restaurant', facility_id: null, service_charge_percent: 0, is_active: true })}>
          {t('restaurant.setup.add_outlet')}
        </Button>
      </Group>
      {outlets.length === 0 ? (
        <EmptyState title={t('restaurant.no_outlet')} />
      ) : (
        <Card padding={0}>
          <Table verticalSpacing="sm">
            <Table.Tbody>
              {outlets.map((o) => (
                <Table.Tr key={o.id} data-outlet={o.code}>
                  <Table.Td>
                    <Text fw={600}>{loc(o.name)}</Text>
                    <Text size="xs" c="dimmed">
                      {o.code} · {t(`restaurant.kinds.${o.kind}`)}
                    </Text>
                  </Table.Td>
                  <Table.Td>{t('restaurant.setup.service_charge_value', { rate: formatNumber(o.service_charge_percent, i18n.language, 2) })}</Table.Td>
                  <Table.Td>
                    <ActiveBadge active={o.is_active} />
                  </Table.Td>
                  <Table.Td w={90}>
                    <Group gap={4} justify="flex-end" wrap="nowrap">
                      <ActionIcon variant="subtle" aria-label={t('common.edit')} onClick={() => setDraft({ ...o, service_charge_percent: Number(o.service_charge_percent) })}>
                        <IconEdit size={16} />
                      </ActionIcon>
                      <ActionIcon
                        variant="subtle"
                        color="red"
                        aria-label={t('common.delete')}
                        onClick={() => confirmDelete({ title: t('restaurant.setup.delete_outlet', { name: loc(o.name) }), onConfirm: () => crud.remove.mutateAsync(o.id).then(() => notifySuccess(t('common.deleted')), notifyError) })}
                      >
                        <IconTrash size={16} />
                      </ActionIcon>
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Card>
      )}
      {draft && <OutletModal draft={draft} crud={crud} onClose={() => setDraft(null)} />}
    </Stack>
  );
}

function OutletModal({ draft, crud, onClose }: { draft: OutletDraft; crud: ReturnType<typeof useCrud<Outlet>>; onClose: () => void }) {
  const { t } = useTranslation();
  const loc = useLocalized();
  const languages = useLanguages();
  const facilities = useHotelQuery<Facility[]>('facility', '/facilities');
  const [v, setV] = useState(draft);
  const [error, setError] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const submit = async () => {
    const { id, version, ...rest } = v;
    const body = { ...rest, service_charge_percent: String(rest.service_charge_percent) };
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
    <Modal opened onClose={onClose} title={draft.id ? t('restaurant.setup.edit_outlet') : t('restaurant.setup.add_outlet')} size="lg">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <Stack>
          {error && <Alert color="red">{error}</Alert>}
          <SimpleGrid cols={2}>
            <TextInput label={t('common.code')} required value={v.code} onChange={(e) => setV({ ...v, code: e.currentTarget.value })} error={errors.code} />
            <Select label={t('restaurant.setup.kind')} allowDeselect={false} data={KINDS.map((k) => ({ value: k, label: t(`restaurant.kinds.${k}`) }))} value={v.kind} onChange={(x) => x && setV({ ...v, kind: x as OutletKind })} />
          </SimpleGrid>
          <LocalizedTextInput label={t('common.name')} required languages={languages} value={v.name} onChange={(x) => setV({ ...v, name: x })} error={errors.name} />
          <SimpleGrid cols={2}>
            <NumberInput label={t('restaurant.setup.service_charge')} description={t('restaurant.setup.service_charge_hint')} min={0} max={100} decimalScale={2} value={v.service_charge_percent} onChange={(x) => setV({ ...v, service_charge_percent: x })} />
            <Select
              label={t('restaurant.setup.facility')}
              description={t('restaurant.setup.facility_hint')}
              clearable
              data={(facilities.data ?? []).map((f) => ({ value: f.id, label: loc(f.name) }))}
              value={v.facility_id}
              onChange={(x) => setV({ ...v, facility_id: x })}
            />
          </SimpleGrid>
          <Text size="xs" c="dimmed">
            {t('restaurant.setup.taxes_hint')}
          </Text>
          <Switch label={t('common.active')} checked={v.is_active} onChange={(e) => setV({ ...v, is_active: e.currentTarget.checked })} />
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <SubmitButton loading={crud.create.isPending || crud.update.isPending} disabled={!v.code.trim()}>
              {t('common.save')}
            </SubmitButton>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

// --- menu ---------------------------------------------------------------------------------

interface ItemDraft {
  id?: string;
  version?: number;
  category_id: string | null;
  code: string;
  name: LocalizedText;
  description: LocalizedText;
  price: number | string;
  station: Station;
  is_available: boolean;
  is_active: boolean;
}

function MenuSection({ outlet }: { outlet: Outlet }) {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const loc = useLocalized();
  const menu = useMenu(outlet.id);
  const categories = useCrud<MenuCategory>('menu_item', '/restaurant/categories');
  const items = useCrud<MenuItem>('menu_item', '/restaurant/menu-items');
  const [category, setCategory] = useState<{ id?: string; version?: number; name: LocalizedText; is_active: boolean } | null>(null);
  const [item, setItem] = useState<ItemDraft | null>(null);
  const [filter, setFilter] = useState<string | null>(null);
  const shown = menu.allItems.filter((i) => !filter || i.category_id === filter);
  return (
    <SimpleGrid cols={{ base: 1, md: 3 }}>
      <Card padding="sm">
        <Group justify="space-between" mb="xs">
          <Text fw={600}>{t('restaurant.setup.categories')}</Text>
          <Button size="xs" variant="light" leftSection={<IconPlus size={14} />} onClick={() => setCategory({ name: {}, is_active: true })}>
            {t('restaurant.setup.add_category')}
          </Button>
        </Group>
        <Stack gap={4}>
          {menu.allCategories.map((c) => (
            <Group key={c.id} justify="space-between" wrap="nowrap" data-category={loc(c.name)}>
              <Button variant={filter === c.id ? 'light' : 'subtle'} size="xs" onClick={() => setFilter(filter === c.id ? null : c.id)} style={{ flex: 1, justifyContent: 'flex-start' }}>
                {loc(c.name)} {!c.is_active && <Badge size="xs" ml={6} color="gray">{t('common.inactive')}</Badge>}
              </Button>
              <ActionIcon variant="subtle" aria-label={t('common.edit')} onClick={() => setCategory({ id: c.id, version: c.version, name: c.name, is_active: c.is_active })}>
                <IconEdit size={14} />
              </ActionIcon>
              <ActionIcon
                variant="subtle"
                color="red"
                aria-label={t('common.delete')}
                onClick={() => confirmDelete({ title: t('restaurant.setup.delete_category', { name: loc(c.name) }), onConfirm: () => categories.remove.mutateAsync(c.id).then(() => notifySuccess(t('common.deleted')), notifyError) })}
              >
                <IconTrash size={14} />
              </ActionIcon>
            </Group>
          ))}
          {menu.allCategories.length === 0 && <Text size="sm" c="dimmed">{t('restaurant.setup.no_categories')}</Text>}
        </Stack>
      </Card>
      <Card padding="sm" style={{ gridColumn: 'span 2' }}>
        <Group justify="space-between" mb="xs">
          <Text fw={600}>{t('restaurant.setup.items')}</Text>
          <Button
            size="xs"
            leftSection={<IconPlus size={14} />}
            disabled={menu.allCategories.length === 0}
            onClick={() => setItem({ category_id: filter ?? menu.allCategories[0]?.id ?? null, code: '', name: {}, description: {}, price: '', station: 'kitchen', is_available: true, is_active: true })}
          >
            {t('restaurant.setup.add_item')}
          </Button>
        </Group>
        <div className="hms-table-wrap">
          <Table verticalSpacing={6} miw={520}>
            <Table.Tbody>
              {shown.map((i) => (
                <Table.Tr key={i.id} data-item={loc(i.name)}>
                  <Table.Td>
                    <Text size="sm" fw={600}>
                      {loc(i.name)}
                    </Text>
                    <Text size="xs" c="dimmed">
                      {loc(menu.allCategories.find((c) => c.id === i.category_id)?.name)} · {t(`restaurant.stations.${i.station}`)}
                    </Text>
                  </Table.Td>
                  <Table.Td className="hms-num">{formatMoney(i.price, hotel.currency_code, i18n.language)}</Table.Td>
                  <Table.Td>
                    {!i.is_active ? <ActiveBadge active={false} /> : !i.is_available && <Badge size="sm" color="red" variant="light">{t('restaurant.sold_out')}</Badge>}
                  </Table.Td>
                  <Table.Td w={80}>
                    <Group gap={4} justify="flex-end" wrap="nowrap">
                      <ActionIcon variant="subtle" aria-label={t('common.edit')} onClick={() => setItem({ ...i, code: i.code ?? '', price: Number(i.price) })}>
                        <IconEdit size={14} />
                      </ActionIcon>
                      <ActionIcon
                        variant="subtle"
                        color="red"
                        aria-label={t('common.delete')}
                        onClick={() => confirmDelete({ title: t('restaurant.setup.delete_item', { name: loc(i.name) }), onConfirm: () => items.remove.mutateAsync(i.id).then(() => notifySuccess(t('common.deleted')), notifyError) })}
                      >
                        <IconTrash size={14} />
                      </ActionIcon>
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </div>
        {shown.length === 0 && <Text size="sm" c="dimmed">{t('restaurant.no_items')}</Text>}
      </Card>
      {category && <CategoryModal outlet={outlet} draft={category} crud={categories} onClose={() => setCategory(null)} />}
      {item && <ItemModal draft={item} categories={menu.allCategories} crud={items} onClose={() => setItem(null)} />}
    </SimpleGrid>
  );
}

function CategoryModal({ outlet, draft, crud, onClose }: { outlet: Outlet; draft: { id?: string; version?: number; name: LocalizedText; is_active: boolean }; crud: ReturnType<typeof useCrud<MenuCategory>>; onClose: () => void }) {
  const { t } = useTranslation();
  const languages = useLanguages();
  const [v, setV] = useState(draft);
  const [error, setError] = useState<string | null>(null);
  return (
    <Modal opened onClose={onClose} title={draft.id ? t('restaurant.setup.edit_category') : t('restaurant.setup.add_category')}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          const p = v.id
            ? crud.update.mutateAsync({ id: v.id, body: { version: v.version, name: v.name, is_active: v.is_active } })
            : crud.create.mutateAsync({ outlet_id: outlet.id, name: v.name, is_active: v.is_active } as never);
          p.then(() => {
            notifySuccess(t('common.saved'));
            onClose();
          }, (err) => setError(errorMessage(err)));
        }}
      >
        <Stack>
          {error && <Alert color="red">{error}</Alert>}
          <LocalizedTextInput label={t('common.name')} required languages={languages} value={v.name} onChange={(x) => setV({ ...v, name: x })} />
          <Switch label={t('common.active')} checked={v.is_active} onChange={(e) => setV({ ...v, is_active: e.currentTarget.checked })} />
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

function ItemModal({ draft, categories, crud, onClose }: { draft: ItemDraft; categories: MenuCategory[]; crud: ReturnType<typeof useCrud<MenuItem>>; onClose: () => void }) {
  const { t } = useTranslation();
  const loc = useLocalized();
  const languages = useLanguages();
  const [v, setV] = useState(draft);
  const [error, setError] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const submit = async () => {
    const { id, version, ...rest } = v;
    const body = { ...rest, code: rest.code.trim() || null, price: String(rest.price) };
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
    <Modal opened onClose={onClose} title={draft.id ? t('restaurant.setup.edit_item') : t('restaurant.setup.add_item')} size="lg">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <Stack>
          {error && <Alert color="red">{error}</Alert>}
          <LocalizedTextInput label={t('common.name')} required languages={languages} value={v.name} onChange={(x) => setV({ ...v, name: x })} error={errors.name} />
          <LocalizedTextInput label={t('restaurant.setup.item_description')} multiline languages={languages} value={v.description} onChange={(x) => setV({ ...v, description: x })} />
          <SimpleGrid cols={{ base: 1, sm: 3 }}>
            <Select label={t('restaurant.setup.category')} allowDeselect={false} data={categories.map((c) => ({ value: c.id, label: loc(c.name) }))} value={v.category_id} onChange={(x) => setV({ ...v, category_id: x })} />
            <NumberInput label={t('restaurant.setup.price')} required min={0} decimalScale={2} value={v.price} onChange={(x) => setV({ ...v, price: x })} error={errors.price} />
            <Select
              label={t('restaurant.setup.station')}
              description={t('restaurant.setup.station_hint')}
              allowDeselect={false}
              data={STATIONS.map((s) => ({ value: s, label: t(`restaurant.stations.${s}`) }))}
              value={v.station}
              onChange={(x) => x && setV({ ...v, station: x as Station })}
            />
          </SimpleGrid>
          <TextInput label={t('common.code')} value={v.code} onChange={(e) => setV({ ...v, code: e.currentTarget.value })} error={errors.code} />
          <Group>
            <Switch label={t('restaurant.setup.available')} checked={v.is_available} onChange={(e) => setV({ ...v, is_available: e.currentTarget.checked })} />
            <Switch label={t('common.active')} checked={v.is_active} onChange={(e) => setV({ ...v, is_active: e.currentTarget.checked })} />
          </Group>
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <SubmitButton loading={crud.create.isPending || crud.update.isPending} disabled={!v.category_id || v.price === ''}>
              {t('common.save')}
            </SubmitButton>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

// --- tables -------------------------------------------------------------------------------

function TablesSection({ outlet }: { outlet: Outlet }) {
  const { t } = useTranslation();
  const tables = useHotelQuery<DiningTable[]>('restaurant_outlet', '/restaurant/tables', { outlet_id: outlet.id });
  const crud = useCrud<DiningTable>('restaurant_outlet', '/restaurant/tables', ['restaurant_outlet', 'restaurant_order']);
  const [draft, setDraft] = useState<{ id?: string; version?: number; label: string; area: string; seats: number | string; is_active: boolean; until?: number | string } | null>(null);
  return (
    <Stack>
      <Group justify="space-between">
        <Text size="sm" c="dimmed">
          {t('restaurant.setup.tables_hint')}
        </Text>
        <Button leftSection={<IconPlus size={16} />} onClick={() => setDraft({ label: '', area: '', seats: 4, is_active: true })}>
          {t('restaurant.setup.add_tables')}
        </Button>
      </Group>
      <SimpleGrid cols={{ base: 2, sm: 4, md: 6 }} spacing="xs">
        {(tables.data ?? []).map((x) => (
          <Card key={x.id} withBorder padding="xs" data-setup-table={x.label}>
            <Group justify="space-between" wrap="nowrap">
              <div>
                <Text fw={700}>{x.label}</Text>
                <Text size="xs" c="dimmed">
                  {x.area ? `${x.area} · ` : ''}
                  {t('restaurant.seats', { count: x.seats })}
                </Text>
              </div>
              <Group gap={2} wrap="nowrap">
                <ActionIcon size="sm" variant="subtle" aria-label={t('common.edit')} onClick={() => setDraft({ ...x, area: x.area ?? '' })}>
                  <IconEdit size={14} />
                </ActionIcon>
                <ActionIcon
                  size="sm"
                  variant="subtle"
                  color="red"
                  aria-label={t('common.delete')}
                  onClick={() => confirmDelete({ title: t('restaurant.setup.delete_table', { table: x.label }), onConfirm: () => crud.remove.mutateAsync(x.id).then(() => notifySuccess(t('common.deleted')), notifyError) })}
                >
                  <IconTrash size={14} />
                </ActionIcon>
              </Group>
            </Group>
            {!x.is_active && <ActiveBadge active={false} />}
          </Card>
        ))}
      </SimpleGrid>
      {draft && (
        <TableModal
          outlet={outlet}
          draft={draft}
          onClose={() => setDraft(null)}
          save={async (body, until) => {
            if (draft.id) {
              await crud.update.mutateAsync({ id: draft.id, body: { ...body, version: draft.version } });
              return;
            }
            // "T1" to "T10": the number at the end of the label is incremented.
            const m = /^(.*?)(\d+)$/.exec(String(body.label));
            if (until && m && Number(until) > Number(m[2])) {
              for (let n = Number(m[2]); n <= Number(until); n++) await crud.create.mutateAsync({ ...body, label: `${m[1]}${n}` } as never);
            } else await crud.create.mutateAsync(body as never);
          }}
        />
      )}
    </Stack>
  );
}

function TableModal({
  outlet,
  draft,
  onClose,
  save,
}: {
  outlet: Outlet;
  draft: { id?: string; label: string; area: string; seats: number | string; is_active: boolean };
  onClose: () => void;
  save: (body: Record<string, unknown>, until?: number | string) => Promise<void>;
}) {
  const { t } = useTranslation();
  const [v, setV] = useState(draft);
  const [until, setUntil] = useState<number | string>('');
  const [error, setError] = useState<string | null>(null);
  return (
    <Modal opened onClose={onClose} title={draft.id ? t('restaurant.setup.edit_table') : t('restaurant.setup.add_tables')}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          save({ outlet_id: draft.id ? undefined : outlet.id, label: v.label.trim(), area: v.area.trim() || null, seats: Number(v.seats), is_active: v.is_active }, until).then(() => {
            notifySuccess(t('common.saved'));
            onClose();
          }, (err) => setError(errorMessage(err)));
        }}
      >
        <Stack>
          {error && <Alert color="red">{error}</Alert>}
          <SimpleGrid cols={2}>
            <TextInput label={t('restaurant.setup.table_label')} placeholder="T1" required maxLength={20} value={v.label} onChange={(e) => setV({ ...v, label: e.currentTarget.value })} />
            {!draft.id && <NumberInput label={t('restaurant.setup.until')} description={t('restaurant.setup.until_hint')} min={1} max={500} value={until} onChange={setUntil} />}
          </SimpleGrid>
          <SimpleGrid cols={2}>
            <TextInput label={t('restaurant.setup.area')} placeholder={t('restaurant.setup.area_placeholder')} maxLength={60} value={v.area} onChange={(e) => setV({ ...v, area: e.currentTarget.value })} />
            <NumberInput label={t('restaurant.setup.seats')} min={1} max={100} value={v.seats} onChange={(x) => setV({ ...v, seats: x })} />
          </SimpleGrid>
          <Switch label={t('common.active')} checked={v.is_active} onChange={(e) => setV({ ...v, is_active: e.currentTarget.checked })} />
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <SubmitButton disabled={!v.label.trim()}>{t('common.save')}</SubmitButton>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}
