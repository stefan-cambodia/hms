import { useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Card,
  Drawer,
  Group,
  Loader,
  Modal,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Text,
  Textarea,
  TextInput,
  Title,
} from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import { useDebouncedValue, useElementSize } from '@mantine/hooks';
import { modals } from '@mantine/modals';
import { IconChevronLeft, IconChevronRight, IconLock, IconPlus, IconSearch } from '@tabler/icons-react';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { api } from '@/api/client';
import { useHotelMutation, useHotelQuery } from '@/api/hooks';
import { hotelKey } from '@/api/realtime';
import type { CalendarData, CalendarItem, Reservation, RoomBlock } from '@/api/types';
import { useAuth, useHotel } from '@/auth/AuthProvider';
import { PageHeader, SubmitButton } from '@/components/ui';
import { addDays, daysBetween } from '@/lib/dates';
import { notifyError, notifySuccess } from '@/lib/errors';
import { formatDate, formatMoney } from '@/lib/format';
import { NewReservationDrawer, type ReservationDraft } from '@/modules/reservations/NewReservationDrawer';
import { FlagBadges, StatusBadge, useHotelToday, useInventory } from '@/modules/reservations/shared';
import { STATUS_COLORS } from './layout';
import { LABEL_W, type MoveRequest, Timeline } from './Timeline';

const PRESETS = { week: 7, two_weeks: 14, month: 31 } as const;
type Preset = keyof typeof PRESETS;
const MIN_COL = { week: 84, two_weeks: 56, month: 40 } as const;

export default function CalendarPage() {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const { can } = useAuth();
  const qc = useQueryClient();
  const today = useHotelToday();
  const inv = useInventory();
  // View state lives in the URL so a calendar view can be bookmarked or shared.
  const [params, setParams] = useSearchParams();
  const preset: Preset = (params.get('view') as Preset) in PRESETS ? (params.get('view') as Preset) : 'two_weeks';
  const start = /^\d{4}-\d{2}-\d{2}$/.test(params.get('start') ?? '') ? params.get('start')! : addDays(today, -1);
  const setView = (next: { start?: string; view?: Preset }) =>
    setParams((p) => {
      const out = new URLSearchParams(p);
      if (next.start) out.set('start', next.start);
      if (next.view) out.set('view', next.view);
      return out;
    }, { replace: true });
  const setStart = (value: string) => setView({ start: value });
  const setPreset = (value: Preset) => setView({ view: value });
  const [category, setCategory] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [highlight] = useDebouncedValue(search, 150);
  const [draft, setDraft] = useState<ReservationDraft | null>(null);
  const [opened, setOpened] = useState<CalendarItem | null>(null);
  const [blocking, setBlocking] = useState(false);
  const { ref, width } = useElementSize();

  const days = PRESETS[preset];
  const end = addDays(start, days);
  const data = useHotelQuery<CalendarData>('calendar', '/calendar', { start, end });
  const colWidth = Math.max(MIN_COL[preset], Math.floor((width - LABEL_W) / days) || MIN_COL[preset]);

  const types = useMemo(() => inv.types.filter((rt) => (!category || rt.id === category) && rt.is_active), [inv.types, category]);

  const move = async (m: MoveRequest) => {
    const room = m.roomId ? inv.roomById.get(m.roomId) : null;
    const otherCategory = room && room.room_type_id !== m.item.room_type_id;
    modals.openConfirmModal({
      title: t('calendar.move_title', { code: m.item.code }),
      children: (
        <Stack gap={6}>
          <Text size="sm">
            {t('calendar.move_body', {
              guest: m.item.guest_name,
              room: room ? room.number : t('reservations.unassigned'),
              from: formatDate(m.start, i18n.language),
              to: formatDate(m.end, i18n.language),
            })}
          </Text>
          {otherCategory && (
            <Text size="sm" c="orange.8">
              {t('calendar.move_other_category', { room: room!.number, category: inv.typeName(room!.room_type_id), booked: inv.typeName(m.item.room_type_id) })}
            </Text>
          )}
          {m.start !== m.item.start && (
            <Text size="xs" c="dimmed">
              {t('reservations.dates_price_hint')}
            </Text>
          )}
        </Stack>
      ),
      labels: { confirm: t('calendar.move_confirm'), cancel: t('common.cancel') },
      onConfirm: async () => {
        try {
          const res = await api.get<Reservation>(`/hotels/${hotel.id}/reservations/${m.item.reservation_id}`);
          await api.post(`/hotels/${hotel.id}/reservations/${res.id}/rooms/${m.item.id}/move`, {
            version: res.version,
            room_id: m.roomId,
            arrival: m.start,
            departure: m.end,
          });
          notifySuccess(t('calendar.moved', { code: res.code }));
        } catch (err) {
          notifyError(err);
        } finally {
          for (const e of ['calendar', 'reservation']) void qc.invalidateQueries({ queryKey: hotelKey(hotel.id, e) });
        }
      },
    });
  };

  const openItem = (it: CalendarItem) => {
    if (it.kind === 'stay') {
      setOpened(it);
      return;
    }
    if (!can('rooms.block')) return;
    modals.openConfirmModal({
      title: t('calendar.remove_block_title', { room: inv.roomNumber(it.room_id) }),
      children: (
        <Text size="sm">
          {t(`calendar.block_reasons.${it.block_reason}`)} · {formatDate(it.start, i18n.language)} → {formatDate(it.end, i18n.language)}
        </Text>
      ),
      labels: { confirm: t('calendar.remove_block'), cancel: t('common.cancel') },
      confirmProps: { color: 'red' },
      onConfirm: () =>
        void api.delete(`/hotels/${hotel.id}/room-blocks/${it.id}`).then(() => {
          notifySuccess(t('calendar.block_removed'));
          void qc.invalidateQueries({ queryKey: hotelKey(hotel.id, 'calendar') });
        }, notifyError),
    });
  };

  return (
    <>
      <PageHeader
        title={t('nav.calendar')}
        actions={
          <>
            {can('rooms.block') && (
              <Button variant="default" leftSection={<IconLock size={16} />} onClick={() => setBlocking(true)}>
                {t('calendar.block_room')}
              </Button>
            )}
            {can('reservations.create') && (
              <Button leftSection={<IconPlus size={16} />} onClick={() => setDraft({ arrival: today, departure: addDays(today, 1) })}>
                {t('reservations.new')}
              </Button>
            )}
          </>
        }
      />
      <Card padding="sm" mb="sm">
        <Group gap="sm" wrap="wrap" justify="space-between">
          <Group gap="xs" wrap="nowrap">
            <ActionIcon variant="default" size="lg" aria-label={t('calendar.previous')} onClick={() => setStart(addDays(start, -Math.max(1, Math.floor(days / 2))))}>
              <IconChevronLeft size={18} />
            </ActionIcon>
            <Button variant="default" onClick={() => setStart(addDays(today, -1))}>
              {t('calendar.today')}
            </Button>
            <ActionIcon variant="default" size="lg" aria-label={t('calendar.next')} onClick={() => setStart(addDays(start, Math.max(1, Math.floor(days / 2))))}>
              <IconChevronRight size={18} />
            </ActionIcon>
            <DatePickerInput value={start} onChange={(v) => v && setStart(v)} valueFormat="D MMM YYYY" w={150} aria-label={t('calendar.start_date')} />
            {data.isFetching && <Loader size="xs" />}
          </Group>
          <Group gap="xs" wrap="wrap">
            <SegmentedControl value={preset} onChange={(v) => setPreset(v as Preset)} data={(Object.keys(PRESETS) as Preset[]).map((p) => ({ value: p, label: t(`calendar.range.${p}`) }))} />
            <Select
              placeholder={t('rooms.all_categories')}
              clearable
              data={inv.types.filter((rt) => rt.is_active).map((rt) => ({ value: rt.id, label: inv.typeName(rt.id) }))}
              value={category}
              onChange={setCategory}
              w={190}
            />
            <TextInput placeholder={t('calendar.find_guest')} leftSection={<IconSearch size={16} />} value={search} onChange={(e) => setSearch(e.currentTarget.value)} w={190} />
          </Group>
        </Group>
      </Card>

      <Group gap="md" mb="xs" wrap="wrap">
        {(['pending', 'confirmed', 'checked_in', 'checked_out'] as const).map((s) => (
          <Group key={s} gap={6} wrap="nowrap">
            <span style={{ width: 12, height: 12, borderRadius: 3, background: `color-mix(in srgb, var(--mantine-color-${STATUS_COLORS[s]}-filled) 20%, var(--mantine-color-body))`, borderLeft: `3px solid var(--mantine-color-${STATUS_COLORS[s]}-filled)` }} />
            <Text size="xs">{t(`reservations.status.${s}`)}</Text>
          </Group>
        ))}
        <Group gap={6} wrap="nowrap">
          <span style={{ width: 12, height: 12, borderRadius: 3, background: 'repeating-linear-gradient(135deg, var(--mantine-color-gray-2) 0 3px, var(--mantine-color-gray-4) 3px 6px)' }} />
          <Text size="xs">{t('calendar.blocked')}</Text>
        </Group>
        <Text size="xs" c="dimmed">
          {can('reservations.edit') ? t('calendar.hint_edit') : t('calendar.hint_view')}
        </Text>
      </Group>

      <Card padding={0} ref={ref}>
        <Box style={{ overflow: 'auto', maxHeight: 'calc(100dvh - 250px)', minHeight: 320, overscrollBehavior: 'contain' }}>
          {data.data && !inv.loading ? (
            <Timeline
              start={start}
              days={days}
              colWidth={colWidth}
              rooms={inv.rooms}
              types={types}
              items={data.data.items}
              unassigned={data.data.unassigned}
              availability={data.data.availability}
              today={today}
              highlight={highlight}
              canCreate={can('reservations.create')}
              canMove={can('reservations.edit')}
              onCreate={(room, date) => setDraft({ arrival: date, departure: addDays(date, 1), room_type_id: room.room_type_id, room_id: room.id })}
              onOpen={openItem}
              onMove={move}
            />
          ) : (
            <Group justify="center" p="xl">
              <Loader />
            </Group>
          )}
        </Box>
      </Card>

      <NewReservationDrawer opened={!!draft} draft={draft ?? undefined} onClose={() => setDraft(null)} onCreated={() => setDraft(null)} />
      <QuickView item={opened} onClose={() => setOpened(null)} />
      {blocking && <BlockRoomModal defaultStart={today} onClose={() => setBlocking(false)} />}
    </>
  );
}

function QuickView({ item, onClose }: { item: CalendarItem | null; onClose: () => void }) {
  const { t, i18n } = useTranslation();
  const inv = useInventory();
  const res = useHotelQuery<Reservation>('reservation', `/reservations/${item?.reservation_id}`, undefined, !!item?.reservation_id);
  const r = res.data;
  return (
    <Drawer opened={!!item} onClose={onClose} title={<Title order={3}>{item?.code}</Title>} size="md">
      {!r ? (
        <Loader />
      ) : (
        <Stack>
          <Group gap="xs">
            <StatusBadge status={r.status} size="lg" />
            <FlagBadges modified={r.is_modified} overbooked={r.is_overbooked} />
          </Group>
          <div>
            <Text fw={650} size="lg">
              {r.booker.first_name} {r.booker.last_name}
            </Text>
            <Text size="sm" c="dimmed">
              {[r.booker.email, r.booker.phone].filter(Boolean).join(' · ') || '—'}
            </Text>
          </div>
          <SimpleGrid cols={2}>
            <Info label={t('reservations.arrival')} value={formatDate(r.arrival, i18n.language)} />
            <Info label={t('reservations.departure')} value={formatDate(r.departure, i18n.language)} />
            <Info label={t('reservations.stay')} value={t('reservations.nights', { count: daysBetween(r.arrival, r.departure) })} />
            <Info label={t('reservations.source')} value={t(`reservations.sources.${r.source}`)} />
          </SimpleGrid>
          <Stack gap={4}>
            {r.rooms.map((rr) => (
              <Group key={rr.id} justify="space-between">
                <Text size="sm">{inv.typeName(rr.room_type_id)}</Text>
                <Badge variant="light" color={rr.room_id ? 'lagoon' : 'orange'} radius="sm">
                  {rr.room_id ? inv.roomNumber(rr.room_id) : t('reservations.unassigned')}
                </Badge>
              </Group>
            ))}
          </Stack>
          {r.special_requests && (
            <Info label={t('reservations.special_requests')} value={r.special_requests} />
          )}
          <Group justify="space-between">
            <Text fw={700}>{t('reservations.total')}</Text>
            <Text fw={700} className="hms-num">
              {formatMoney(r.grand_total, r.currency, i18n.language)}
            </Text>
          </Group>
          <Button component={Link} to={`/reservations/${r.id}`}>
            {t('calendar.open_reservation')}
          </Button>
        </Stack>
      )}
    </Drawer>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      <Text size="sm" fw={500} style={{ whiteSpace: 'pre-wrap' }}>
        {value}
      </Text>
    </div>
  );
}

const BLOCK_REASONS = ['maintenance', 'out_of_service', 'owner_use', 'other'] as const;

function BlockRoomModal({ defaultStart, onClose }: { defaultStart: string; onClose: () => void }) {
  const { t } = useTranslation();
  const inv = useInventory();
  const [roomId, setRoomId] = useState<string | null>(null);
  const [dates, setDates] = useState<[string | null, string | null]>([defaultStart, addDays(defaultStart, 1)]);
  const [reason, setReason] = useState<(typeof BLOCK_REASONS)[number]>('maintenance');
  const [notes, setNotes] = useState('');
  const create = useHotelMutation<Record<string, unknown>, RoomBlock>((h, body) => api.post<RoomBlock>(h('/room-blocks'), body), ['calendar']);
  const valid = roomId && dates[0] && dates[1] && dates[1] > dates[0];
  return (
    <Modal opened onClose={onClose} title={t('calendar.block_room')}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!valid) return;
          void create
            .mutateAsync({ room_id: roomId, start_date: dates[0], end_date: dates[1], reason, notes: notes.trim() || null })
            .then(() => {
              notifySuccess(t('calendar.block_created'));
              onClose();
            }, notifyError);
        }}
      >
        <Stack>
          <Text size="sm" c="dimmed">
            {t('calendar.block_hint')}
          </Text>
          <Select
            label={t('rooms.number')}
            searchable
            required
            data={inv.rooms.filter((r) => r.is_active).map((r) => ({ value: r.id, label: `${r.number} · ${inv.typeName(r.room_type_id)}` }))}
            value={roomId}
            onChange={setRoomId}
          />
          <DatePickerInput type="range" label={t('calendar.block_dates')} required value={dates} onChange={(v) => setDates([v[0], v[1]])} allowSingleDateInRange={false} />
          <Select
            label={t('calendar.block_reason')}
            allowDeselect={false}
            data={BLOCK_REASONS.map((r) => ({ value: r, label: t(`calendar.block_reasons.${r}`) }))}
            value={reason}
            onChange={(v) => v && setReason(v as (typeof BLOCK_REASONS)[number])}
          />
          <Textarea label={t('rooms.notes')} autosize minRows={2} value={notes} onChange={(e) => setNotes(e.currentTarget.value)} />
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <SubmitButton loading={create.isPending} disabled={!valid}>
              {t('calendar.block_room')}
            </SubmitButton>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}
