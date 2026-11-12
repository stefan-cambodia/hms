import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import {
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Divider,
  Drawer,
  Group,
  NumberInput,
  Pagination,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Table,
  TagsInput,
  Text,
  Textarea,
  TextInput,
  Title,
} from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import { useDebouncedValue } from '@mantine/hooks';
import { IconLock, IconPlus, IconSearch } from '@tabler/icons-react';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { api, ApiError } from '@/api/client';
import { useHotelQuery } from '@/api/hooks';
import { hotelKey } from '@/api/realtime';
import type { Guest, GuestDuplicate, Page, ReservationListItem } from '@/api/types';
import { useAuth, useHotel } from '@/auth/AuthProvider';
import { EmptyState, PageHeader, SubmitButton } from '@/components/ui';
import { LANGUAGES } from '@/i18n';
import { errorMessage, fieldMessage, notifySuccess } from '@/lib/errors';
import { countryName, formatDate, formatMoney } from '@/lib/format';
import { COUNTRY_CODES } from '@/lib/refdata';
import { guestLabel } from '@/modules/reservations/GuestPicker';
import { StatusBadge } from '@/modules/reservations/shared';

const PAGE = 50;
const ID_TYPES = ['passport', 'national_id', 'driving_licence', 'residence_permit', 'other'] as const;

export default function GuestsPage() {
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState('');
  const [q] = useDebouncedValue(search, 250);
  const [page, setPage] = useState(1);
  const list = useHotelQuery<Page<Guest>>('guest', '/guests', { q, limit: PAGE, offset: (page - 1) * PAGE });
  const openId = params.get('id');
  const [creating, setCreating] = useState(false);
  const total = list.data?.total ?? 0;

  return (
    <>
      <PageHeader
        title={t('nav.guests')}
        description={t('guests.description')}
        actions={
          can('guests.edit') && (
            <Button leftSection={<IconPlus size={16} />} onClick={() => setCreating(true)}>
              {t('guests.add')}
            </Button>
          )
        }
      />
      <Card mb="md" padding="md">
        <TextInput
          placeholder={t('guests.search')}
          leftSection={<IconSearch size={16} />}
          value={search}
          onChange={(e) => {
            setSearch(e.currentTarget.value);
            setPage(1);
          }}
          maw={420}
        />
      </Card>
      {list.isSuccess && total === 0 ? (
        <EmptyState title={t('guests.empty')} />
      ) : (
        <Card padding={0}>
          <div className="hms-table-wrap">
            <Table miw={560} highlightOnHover>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t('common.name')}</Table.Th>
                  <Table.Th>{t('guests.contact')}</Table.Th>
                  <Table.Th visibleFrom="sm">{t('guests.nationality')}</Table.Th>
                  <Table.Th visibleFrom="md">{t('guests.since')}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {list.data?.items.map((g) => (
                  <Table.Tr key={g.id} style={{ cursor: 'pointer' }} onClick={() => setParams({ id: g.id })}>
                    <Table.Td>
                      <Group gap={6} wrap="nowrap">
                        <Text size="sm" fw={600}>
                          {g.first_name} {g.last_name}
                        </Text>
                        {g.vip_level > 0 && (
                          <Badge size="xs" color="brass" variant="light">
                            VIP {g.vip_level}
                          </Badge>
                        )}
                      </Group>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm">{g.email ?? '—'}</Text>
                      <Text size="xs" c="dimmed">
                        {g.phone}
                      </Text>
                    </Table.Td>
                    <Table.Td visibleFrom="sm">{countryName(g.nationality, i18n.language)}</Table.Td>
                    <Table.Td visibleFrom="md">{formatDate(g.created_at, i18n.language)}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </div>
        </Card>
      )}
      {total > PAGE && (
        <Group justify="center" mt="md">
          <Pagination total={Math.ceil(total / PAGE)} value={page} onChange={setPage} />
        </Group>
      )}
      <GuestDrawer guestId={creating ? 'new' : openId} onClose={() => (creating ? setCreating(false) : setParams({}))} onCreated={(g) => {
        setCreating(false);
        setParams({ id: g.id });
      }} />
    </>
  );
}

type Form = {
  first_name: string;
  last_name: string;
  email: string;
  phone: string;
  nationality: string | null;
  preferred_language: string | null;
  address: string;
  city: string;
  country_code: string | null;
  vip_level: number;
  tags: string[];
  notes: string;
  marketing_consent: boolean;
  date_of_birth: string | null;
  id_document_type: string | null;
  id_document_number: string;
  id_document_country: string | null;
  id_document_expiry: string | null;
};

const EMPTY: Form = {
  first_name: '', last_name: '', email: '', phone: '', nationality: null, preferred_language: null, address: '', city: '',
  country_code: null, vip_level: 0, tags: [], notes: '', marketing_consent: false, date_of_birth: null, id_document_type: null,
  id_document_number: '', id_document_country: null, id_document_expiry: null,
};

function toForm(g: Guest): Form {
  return {
    first_name: g.first_name, last_name: g.last_name, email: g.email ?? '', phone: g.phone ?? '', nationality: g.nationality,
    preferred_language: g.preferred_language, address: g.address ?? '', city: g.city ?? '', country_code: g.country_code,
    vip_level: g.vip_level, tags: g.tags, notes: g.notes ?? '', marketing_consent: g.marketing_consent, date_of_birth: g.date_of_birth,
    id_document_type: g.id_document_type, id_document_number: g.id_document_number ?? '', id_document_country: g.id_document_country,
    id_document_expiry: g.id_document_expiry,
  };
}

function GuestDrawer({ guestId, onClose, onCreated }: { guestId: string | null; onClose: () => void; onCreated: (g: Guest) => void }) {
  const { t } = useTranslation();
  const isNew = guestId === 'new';
  const guest = useHotelQuery<Guest>('guest', `/guests/${guestId}`, undefined, !!guestId && !isNew);
  return (
    <Drawer opened={!!guestId} onClose={onClose} size="xl" title={<Title order={3}>{isNew ? t('guests.add') : guest.data ? `${guest.data.first_name} ${guest.data.last_name}` : ''}</Title>}>
      {guestId && (isNew || guest.data) && <GuestForm key={guestId + (guest.data?.version ?? '')} guest={isNew ? null : guest.data!} onSaved={(g) => (isNew ? onCreated(g) : undefined)} />}
      {guestId && !isNew && guest.data && <GuestReservations guestId={guest.data.id} />}
    </Drawer>
  );
}

function GuestForm({ guest, onSaved }: { guest: Guest | null; onSaved: (g: Guest) => void }) {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const { can } = useAuth();
  const qc = useQueryClient();
  const [form, setForm] = useState<Form>(guest ? toForm(guest) : EMPTY);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const canEdit = can('guests.edit');
  const sensitive = can('guests.view_sensitive');
  const set = (patch: Partial<Form>) => setForm((f) => ({ ...f, ...patch }));

  const [dupParams] = useDebouncedValue({ first_name: form.first_name.trim(), last_name: form.last_name.trim(), email: form.email.trim() || undefined, phone: form.phone.trim() || undefined, exclude_id: guest?.id }, 400);
  const dups = useHotelQuery<GuestDuplicate[]>('guest', '/guests/duplicates', dupParams, !!(dupParams.first_name && dupParams.last_name) && canEdit);

  const countries = useMemo(
    () => COUNTRY_CODES.map((c) => ({ value: c, label: countryName(c, i18n.language) })).sort((a, b) => a.label.localeCompare(b.label, i18n.language)),
    [i18n.language],
  );
  useEffect(() => setErrors({}), [guest?.id]);

  const submit = async () => {
    setBusy(true);
    setErrors({});
    const body: Record<string, unknown> = {
      first_name: form.first_name.trim(), last_name: form.last_name.trim(), email: form.email.trim() || null, phone: form.phone.trim() || null,
      nationality: form.nationality, preferred_language: form.preferred_language, address: form.address.trim() || null, city: form.city.trim() || null,
      country_code: form.country_code, vip_level: form.vip_level, tags: form.tags, notes: form.notes.trim() || null, marketing_consent: form.marketing_consent,
    };
    if (sensitive) {
      Object.assign(body, {
        date_of_birth: form.date_of_birth, id_document_type: form.id_document_type, id_document_number: form.id_document_number.trim() || null,
        id_document_country: form.id_document_country, id_document_expiry: form.id_document_expiry,
      });
    }
    try {
      const saved = guest
        ? await api.patch<Guest>(`/hotels/${hotel.id}/guests/${guest.id}`, { ...body, version: guest.version })
        : await api.post<Guest>(`/hotels/${hotel.id}/guests`, body);
      void qc.invalidateQueries({ queryKey: hotelKey(hotel.id, 'guest') });
      notifySuccess(t('common.saved'));
      onSaved(saved);
    } catch (err) {
      if (err instanceof ApiError && err.fields.length) {
        setErrors(Object.fromEntries(err.fields.map((f) => [String(f.loc[f.loc.length - 1]), fieldMessage(f.code, f.ctx)])));
      } else {
        setErrors({ _: errorMessage(err) });
      }
    } finally {
      setBusy(false);
    }
  };

  const otherDups = (dups.data ?? []).filter((d) => d.guest.id !== guest?.id);

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <fieldset disabled={!canEdit} style={{ border: 0, padding: 0, margin: 0 }}>
        <Stack>
          {errors._ && <Alert color="red">{errors._}</Alert>}
          {otherDups.length > 0 && (
            <Alert color="yellow" variant="light" title={t('reservations.form.possible_duplicate')}>
              {otherDups.slice(0, 3).map((d) => (
                <Text key={d.guest.id} size="sm">
                  <Anchor component={Link} to={`/guests?id=${d.guest.id}`}>
                    {guestLabel(d.guest)}
                  </Anchor>{' '}
                  <Text span size="xs" c="dimmed">
                    ({d.reasons.map((r) => t(`guests.duplicate_reason.${r}`)).join(', ')})
                  </Text>
                </Text>
              ))}
            </Alert>
          )}
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <TextInput label={t('guests.first_name')} required value={form.first_name} onChange={(e) => set({ first_name: e.currentTarget.value })} error={errors.first_name} />
            <TextInput label={t('guests.last_name')} required value={form.last_name} onChange={(e) => set({ last_name: e.currentTarget.value })} error={errors.last_name} />
            <TextInput label={t('guests.email')} type="email" value={form.email} onChange={(e) => set({ email: e.currentTarget.value })} error={errors.email} />
            <TextInput label={t('guests.phone')} type="tel" value={form.phone} onChange={(e) => set({ phone: e.currentTarget.value })} error={errors.phone} />
            <Select label={t('guests.nationality')} searchable clearable data={countries} value={form.nationality} onChange={(v) => set({ nationality: v })} />
            <Select label={t('guests.preferred_language')} clearable data={LANGUAGES.map((l) => ({ value: l.code, label: l.label }))} value={form.preferred_language} onChange={(v) => set({ preferred_language: v })} />
            <TextInput label={t('guests.address')} value={form.address} onChange={(e) => set({ address: e.currentTarget.value })} />
            <TextInput label={t('guests.city')} value={form.city} onChange={(e) => set({ city: e.currentTarget.value })} />
            <Select label={t('guests.country')} searchable clearable data={countries} value={form.country_code} onChange={(v) => set({ country_code: v })} />
            <NumberInput label={t('guests.vip_level')} description={t('guests.vip_hint')} min={0} max={5} value={form.vip_level} onChange={(v) => set({ vip_level: Number(v) || 0 })} />
          </SimpleGrid>
          <TagsInput label={t('guests.tags')} description={t('guests.tags_hint')} value={form.tags} onChange={(v) => set({ tags: v.slice(0, 20) })} />
          <Textarea label={t('guests.notes')} description={t('guests.notes_hint')} autosize minRows={2} value={form.notes} onChange={(e) => set({ notes: e.currentTarget.value })} />
          <Switch label={t('guests.marketing_consent')} checked={form.marketing_consent} onChange={(e) => set({ marketing_consent: e.currentTarget.checked })} />
          <Divider label={<Group gap={4}><IconLock size={12} />{t('guests.identity')}</Group>} labelPosition="left" />
          {sensitive ? (
            <SimpleGrid cols={{ base: 1, sm: 2 }}>
              <Select label={t('guests.id_document_type')} clearable data={ID_TYPES.map((x) => ({ value: x, label: t(`guests.id_types.${x}`) }))} value={form.id_document_type} onChange={(v) => set({ id_document_type: v })} />
              <TextInput label={t('guests.id_document_number')} value={form.id_document_number} onChange={(e) => set({ id_document_number: e.currentTarget.value })} />
              <Select label={t('guests.id_document_country')} searchable clearable data={countries} value={form.id_document_country} onChange={(v) => set({ id_document_country: v })} />
              <DatePickerInput label={t('guests.id_document_expiry')} clearable value={form.id_document_expiry} onChange={(v) => set({ id_document_expiry: v })} />
              <DatePickerInput label={t('guests.date_of_birth')} clearable value={form.date_of_birth} onChange={(v) => set({ date_of_birth: v })} maxDate={new Date().toISOString().slice(0, 10)} />
            </SimpleGrid>
          ) : (
            <Text size="sm" c="dimmed">
              {guest?.has_id_document ? t('guests.identity_on_file') : t('guests.identity_hidden')}
            </Text>
          )}
          {canEdit && (
            <Group justify="flex-end">
              <SubmitButton loading={busy}>{guest ? t('common.save_changes') : t('guests.add')}</SubmitButton>
            </Group>
          )}
        </Stack>
      </fieldset>
    </form>
  );
}

function GuestReservations({ guestId }: { guestId: string }) {
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const list = useHotelQuery<Page<ReservationListItem>>('reservation', '/reservations', { guest_id: guestId, limit: 100 }, can('reservations.view'));
  if (!can('reservations.view')) return null;
  const stays = list.data?.items ?? [];
  const spent = stays.filter((r) => r.status === 'checked_out').reduce((s, r) => s + Number(r.grand_total), 0);
  return (
    <Stack mt="xl" gap="xs">
      <Group justify="space-between">
        <Title order={4}>{t('guests.history')}</Title>
        {stays[0] && (
          <Text size="sm" c="dimmed">
            {t('guests.history_summary', { count: stays.length, spent: formatMoney(spent, stays[0].currency, i18n.language) })}
          </Text>
        )}
      </Group>
      {stays.length === 0 ? (
        <Text size="sm" c="dimmed">
          {t('guests.no_history')}
        </Text>
      ) : (
        <Table>
          <Table.Tbody>
            {stays.map((r) => (
              <Table.Tr key={r.id}>
                <Table.Td>
                  <Anchor component={Link} to={`/reservations/${r.id}`} fw={600} size="sm" className="hms-num">
                    {r.code}
                  </Anchor>
                </Table.Td>
                <Table.Td>
                  <Text size="sm">
                    {formatDate(r.arrival, i18n.language)} → {formatDate(r.departure, i18n.language)}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <StatusBadge status={r.status} />
                </Table.Td>
                <Table.Td ta="right" className="hms-num">
                  {formatMoney(r.grand_total, r.currency, i18n.language)}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
    </Stack>
  );
}
