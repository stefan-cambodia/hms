import { useState } from 'react';
import { Link, useParams } from 'react-router';
import {
  Anchor,
  Badge,
  Button,
  Card,
  Collapse,
  Divider,
  Grid,
  Group,
  Modal,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Textarea,
  TextInput,
  Timeline,
  Title,
  UnstyledButton,
} from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import { modals } from '@mantine/modals';
import {
  IconArrowLeft,
  IconBed,
  IconCalendarEvent,
  IconCheck,
  IconChevronDown,
  IconCirclePlus,
  IconEdit,
  IconPencil,
  IconStatusChange,
  IconX,
} from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { api } from '@/api/client';
import { useHotelMutation, useHotelQuery } from '@/api/hooks';
import type { AvailableRoom, Reservation, ReservationEvent, ReservationRoom, ReservationSource } from '@/api/types';
import { PageLoader } from '@/app/AppLayout';
import { useAuth, useHotel } from '@/auth/AuthProvider';
import { EmptyState, SubmitButton } from '@/components/ui';
import { daysBetween } from '@/lib/dates';
import { notifyError, notifySuccess } from '@/lib/errors';
import { countryName, formatDate, formatDateTime, formatMoney } from '@/lib/format';
import { pickLocalized } from '@/lib/localized';
import { FlagBadges, SOURCES, StatusBadge, useHotelToday, useInventory } from './shared';

const INVALIDATES = ['reservation', 'calendar'];

export default function ReservationDetailPage() {
  const { id } = useParams();
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const { can } = useAuth();
  const today = useHotelToday();
  const res = useHotelQuery<Reservation>('reservation', `/reservations/${id}`);
  const history = useHotelQuery<ReservationEvent[]>('reservation', `/reservations/${id}/events`);
  const [cancelling, setCancelling] = useState(false);
  const [editing, setEditing] = useState(false);

  const action = useHotelMutation<{ path: string; body: Record<string, unknown> }, Reservation>(
    (h, { path, body }) => api.post<Reservation>(h(`/reservations/${id}/${path}`), body),
    INVALIDATES,
  );

  if (res.isPending) return <PageLoader />;
  if (!res.data) return <EmptyState title={t('reservations.not_found')} action={<Anchor component={Link} to="/reservations">{t('reservations.back')}</Anchor>} />;
  const r = res.data;
  const open = r.status === 'pending' || r.status === 'confirmed';
  const canEdit = can('reservations.edit') && (open || r.status === 'checked_in');
  const run = (path: string, body: Record<string, unknown>, done: string) =>
    action.mutateAsync({ path, body: { version: r.version, ...body } }).then(() => notifySuccess(done), notifyError);

  return (
    <>
      <Anchor component={Link} to="/reservations" size="sm" c="dimmed">
        <Group gap={4}>
          <IconArrowLeft size={14} />
          {t('reservations.back')}
        </Group>
      </Anchor>
      <Group justify="space-between" align="flex-start" mt="xs" mb="lg" wrap="wrap" gap="sm">
        <div>
          <Group gap="sm">
            <Title order={1} className="hms-num">
              {r.code}
            </Title>
            <StatusBadge status={r.status} size="lg" />
            <FlagBadges modified={r.is_modified} overbooked={r.is_overbooked} />
          </Group>
          <Text c="dimmed" size="sm" mt={4}>
            {r.booker.first_name} {r.booker.last_name} · {formatDate(r.arrival, i18n.language)} → {formatDate(r.departure, i18n.language)} ·{' '}
            {t(`reservations.sources.${r.source}`)}
            {r.external_ref ? ` · ${r.external_ref}` : ''}
          </Text>
        </div>
        <Group gap="xs">
          {can('reservations.edit') && r.status === 'pending' && (
            <Button leftSection={<IconCheck size={16} />} loading={action.isPending} onClick={() => run('confirm', {}, t('reservations.confirmed_done'))}>
              {t('reservations.actions.confirm')}
            </Button>
          )}
          {can('reservations.edit') && open && r.arrival <= today && (
            <Button
              variant="default"
              onClick={() =>
                modals.openConfirmModal({
                  title: t('reservations.actions.no_show'),
                  children: <Text size="sm">{t('reservations.no_show_body')}</Text>,
                  labels: { confirm: t('reservations.actions.no_show'), cancel: t('common.cancel') },
                  confirmProps: { color: 'red' },
                  onConfirm: () => void run('no-show', {}, t('reservations.no_show_done')),
                })
              }
            >
              {t('reservations.actions.no_show')}
            </Button>
          )}
          {can('reservations.edit') && r.status !== 'cancelled' && (
            <Button variant="default" leftSection={<IconEdit size={16} />} onClick={() => setEditing(true)}>
              {t('reservations.actions.edit')}
            </Button>
          )}
          {can('reservations.cancel') && open && (
            <Button variant="light" color="red" leftSection={<IconX size={16} />} onClick={() => setCancelling(true)}>
              {t('reservations.actions.cancel')}
            </Button>
          )}
        </Group>
      </Group>

      {r.status === 'cancelled' && (
        <Card mb="md" bg="var(--mantine-color-red-light)" padding="sm">
          <Text size="sm">
            {t('reservations.cancelled_on', { date: formatDateTime(r.cancelled_at, i18n.language, hotel.timezone) })}
            {r.cancellation_reason ? ` — ${r.cancellation_reason}` : ''}
          </Text>
        </Card>
      )}

      <Grid gutter="lg">
        <Grid.Col span={{ base: 12, lg: 8 }}>
          <Stack gap="md">
            {r.rooms.map((rr, i) => (
              <StayCard key={rr.id} reservation={r} stay={rr} index={i} editable={canEdit} />
            ))}
            {(r.special_requests || r.internal_notes) && (
              <Card>
                <SimpleGrid cols={{ base: 1, sm: 2 }}>
                  <div>
                    <Text size="xs" c="dimmed" fw={600} tt="uppercase">
                      {t('reservations.special_requests')}
                    </Text>
                    <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>
                      {r.special_requests || '—'}
                    </Text>
                  </div>
                  <div>
                    <Text size="xs" c="dimmed" fw={600} tt="uppercase">
                      {t('reservations.internal_notes')}
                    </Text>
                    <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>
                      {r.internal_notes || '—'}
                    </Text>
                  </div>
                </SimpleGrid>
              </Card>
            )}
            <Card>
              <Title order={3} mb="md">
                {t('reservations.history')}
              </Title>
              <HistoryTimeline events={history.data ?? []} />
            </Card>
          </Stack>
        </Grid.Col>
        <Grid.Col span={{ base: 12, lg: 4 }}>
          <Stack gap="md">
            <Card>
              <Title order={4} mb="xs">
                {t('reservations.guest')}
              </Title>
              <Text fw={600}>
                {r.booker.first_name} {r.booker.last_name}{' '}
                {r.booker.vip_level > 0 && (
                  <Badge color="brass" size="sm" variant="light">
                    VIP {r.booker.vip_level}
                  </Badge>
                )}
              </Text>
              <Text size="sm" c="dimmed">
                {[r.booker.email, r.booker.phone, r.booker.nationality && countryName(r.booker.nationality, i18n.language)].filter(Boolean).join(' · ') || '—'}
              </Text>
              {can('guests.view') && (
                <Anchor component={Link} to={`/guests?id=${r.booker.id}`} size="sm" mt="xs" display="inline-block">
                  {t('reservations.open_guest')}
                </Anchor>
              )}
            </Card>
            <Card>
              <Title order={4} mb="xs">
                {t('reservations.charges')}
              </Title>
              <Stack gap={6}>
                <Row label={t('reservations.accommodation')} value={formatMoney(r.accommodation_total, r.currency, i18n.language)} />
                {r.tax_breakdown.map((tax) => (
                  <Row
                    key={tax.code}
                    dimmed
                    label={`${pickLocalized(tax.name, i18n.language, hotel.default_language)}${tax.is_inclusive ? ` (${t('settings.taxes.included')})` : ''}`}
                    value={formatMoney(tax.amount, r.currency, i18n.language)}
                  />
                ))}
                <Divider />
                <Row strong label={t('reservations.total')} value={formatMoney(r.grand_total, r.currency, i18n.language)} />
                <Row dimmed label={t('reservations.paid')} value={formatMoney(r.paid_total, r.currency, i18n.language)} />
                <Row strong label={t('reservations.balance')} value={formatMoney(r.balance, r.currency, i18n.language)} />
              </Stack>
              <Text size="xs" c="dimmed" mt="sm">
                {t('reservations.payments_later')}
              </Text>
            </Card>
          </Stack>
        </Grid.Col>
      </Grid>

      {cancelling && (
        <CancelModal
          onClose={() => setCancelling(false)}
          onConfirm={(reason) => run('cancel', { reason }, t('reservations.cancelled_done')).then(() => setCancelling(false))}
          loading={action.isPending}
        />
      )}
      {editing && <EditDetailsModal reservation={r} onClose={() => setEditing(false)} />}
    </>
  );
}

function Row({ label, value, strong, dimmed }: { label: string; value: string; strong?: boolean; dimmed?: boolean }) {
  return (
    <Group justify="space-between" wrap="nowrap">
      <Text size="sm" fw={strong ? 700 : undefined} c={dimmed ? 'dimmed' : undefined}>
        {label}
      </Text>
      <Text size="sm" fw={strong ? 700 : undefined} c={dimmed ? 'dimmed' : undefined} className="hms-num">
        {value}
      </Text>
    </Group>
  );
}

function StayCard({ reservation: r, stay, index, editable }: { reservation: Reservation; stay: ReservationRoom; index: number; editable: boolean }) {
  const { t, i18n } = useTranslation();
  const inv = useInventory();
  const [showNights, setShowNights] = useState(false);
  const [changingDates, setChangingDates] = useState(false);
  const live = stay.occupies_inventory;
  const free = useHotelQuery<AvailableRoom[]>(
    'calendar',
    '/available-rooms',
    { start: stay.arrival, end: stay.departure, room_type_id: stay.room_type_id, ignore_reservation_room: stay.id },
    editable && live && !stay.checked_in_at,
  );
  const assign = useHotelMutation<string | null, Reservation>(
    (h, roomId) => api.post<Reservation>(h(`/reservations/${r.id}/rooms/${stay.id}/assign`), { version: r.version, room_id: roomId }),
    INVALIDATES,
  );
  const options = [
    { value: '', label: t('reservations.form.assign_later') },
    ...(free.data ?? []).map((room) => ({ value: room.id, label: room.number })),
  ];
  if (stay.room_id && !options.some((o) => o.value === stay.room_id)) options.push({ value: stay.room_id, label: inv.roomNumber(stay.room_id) ?? '?' });

  return (
    <Card>
      <Group justify="space-between" align="flex-start" wrap="wrap" gap="sm">
        <Group gap="sm" wrap="nowrap">
          <IconBed size={22} stroke={1.5} />
          <div>
            <Text fw={650}>
              {r.rooms.length > 1 ? `${index + 1}. ` : ''}
              {inv.typeName(stay.room_type_id)}
            </Text>
            <Text size="sm" c="dimmed">
              {formatDate(stay.arrival, i18n.language)} → {formatDate(stay.departure, i18n.language)} · {t('reservations.nights', { count: daysBetween(stay.arrival, stay.departure) })} ·{' '}
              {t('reservations.guests_count', { adults: stay.adults, children: stay.children })}
            </Text>
          </div>
        </Group>
        <Group gap="xs" wrap="nowrap">
          {editable && live && !stay.checked_in_at ? (
            <Select
              aria-label={t('rooms.number')}
              w={150}
              data={options}
              value={stay.room_id ?? ''}
              onChange={(v) => assign.mutateAsync(v || null).then(() => notifySuccess(t('reservations.room_saved')), notifyError)}
              disabled={assign.isPending}
              allowDeselect={false}
            />
          ) : (
            <Badge size="lg" variant="light" radius="sm" color={stay.room_id ? 'lagoon' : 'orange'}>
              {stay.room_id ? inv.roomNumber(stay.room_id) : t('reservations.unassigned')}
            </Badge>
          )}
          {editable && live && (
            <Button variant="default" leftSection={<IconCalendarEvent size={16} />} onClick={() => setChangingDates(true)}>
              {t('reservations.actions.change_dates')}
            </Button>
          )}
        </Group>
      </Group>
      <UnstyledButton mt="sm" onClick={() => setShowNights((s) => !s)}>
        <Group gap={4}>
          <Text size="sm" c="lagoon">
            {t('reservations.nightly_prices')} · {formatMoney(stay.accommodation_total, r.currency, i18n.language)}
          </Text>
          <IconChevronDown size={14} style={{ transform: showNights ? 'rotate(180deg)' : undefined }} />
        </Group>
      </UnstyledButton>
      <Collapse in={showNights}>
        <Table mt="xs" withRowBorders={false} verticalSpacing={2}>
          <Table.Tbody>
            {stay.nights.map((n) => (
              <Table.Tr key={n.night}>
                <Table.Td>
                  <Text size="sm">{formatDate(n.night, i18n.language)}</Text>
                </Table.Td>
                <Table.Td ta="right" className="hms-num">
                  <Text size="sm">{formatMoney(n.price, r.currency, i18n.language)}</Text>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Collapse>
      {changingDates && <ChangeDatesModal reservation={r} stay={stay} onClose={() => setChangingDates(false)} />}
    </Card>
  );
}

function ChangeDatesModal({ reservation: r, stay, onClose }: { reservation: Reservation; stay: ReservationRoom; onClose: () => void }) {
  const { t } = useTranslation();
  const [dates, setDates] = useState<[string | null, string | null]>([stay.arrival, stay.departure]);
  const save = useHotelMutation<[string, string], Reservation>(
    (h, [arrival, departure]) => api.post<Reservation>(h(`/reservations/${r.id}/rooms/${stay.id}/dates`), { version: r.version, arrival, departure }),
    INVALIDATES,
  );
  const valid = dates[0] && dates[1] && dates[1] > dates[0];
  return (
    <Modal opened onClose={onClose} title={t('reservations.actions.change_dates')}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!valid) return;
          void save.mutateAsync([dates[0]!, dates[1]!]).then(() => {
            notifySuccess(t('reservations.dates_saved'));
            onClose();
          }, notifyError);
        }}
      >
        <Stack>
          <DatePickerInput
            type="range"
            label={t('reservations.form.dates')}
            value={dates}
            onChange={(v) => setDates([v[0], v[1]])}
            allowSingleDateInRange={false}
            minDate={stay.checked_in_at ? stay.arrival : undefined}
            valueFormat="ddd D MMM YYYY"
          />
          <Text size="xs" c="dimmed">
            {t('reservations.dates_price_hint')}
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <SubmitButton loading={save.isPending} disabled={!valid}>
              {t('common.save')}
            </SubmitButton>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

function CancelModal({ onClose, onConfirm, loading }: { onClose: () => void; onConfirm: (reason: string) => void; loading: boolean }) {
  const { t } = useTranslation();
  const [reason, setReason] = useState('');
  return (
    <Modal opened onClose={onClose} title={t('reservations.actions.cancel')}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (reason.trim()) onConfirm(reason.trim());
        }}
      >
        <Stack>
          <Text size="sm">{t('reservations.cancel_body')}</Text>
          <Textarea label={t('reservations.cancel_reason')} required autosize minRows={2} value={reason} onChange={(e) => setReason(e.currentTarget.value)} data-autofocus />
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <SubmitButton color="red" loading={loading} disabled={!reason.trim()}>
              {t('reservations.actions.cancel')}
            </SubmitButton>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

function EditDetailsModal({ reservation: r, onClose }: { reservation: Reservation; onClose: () => void }) {
  const { t } = useTranslation();
  const [source, setSource] = useState<ReservationSource>(r.source);
  const [externalRef, setExternalRef] = useState(r.external_ref ?? '');
  const [requests, setRequests] = useState(r.special_requests ?? '');
  const [notes, setNotes] = useState(r.internal_notes ?? '');
  const save = useHotelMutation<Record<string, unknown>, Reservation>((h, body) => api.patch<Reservation>(h(`/reservations/${r.id}`), body), INVALIDATES);
  return (
    <Modal opened onClose={onClose} title={t('reservations.actions.edit')} size="lg">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void save
            .mutateAsync({ version: r.version, source, external_ref: externalRef.trim() || null, special_requests: requests.trim() || null, internal_notes: notes.trim() || null })
            .then(() => {
              notifySuccess(t('common.saved'));
              onClose();
            }, notifyError);
        }}
      >
        <Stack>
          <SimpleGrid cols={2}>
            <Select
              label={t('reservations.source')}
              allowDeselect={false}
              data={SOURCES.map((s) => ({ value: s, label: t(`reservations.sources.${s}`) }))}
              value={source}
              onChange={(v) => v && setSource(v as ReservationSource)}
            />
            <TextInput label={t('reservations.external_ref')} value={externalRef} onChange={(e) => setExternalRef(e.currentTarget.value)} />
          </SimpleGrid>
          <Textarea label={t('reservations.special_requests')} autosize minRows={2} value={requests} onChange={(e) => setRequests(e.currentTarget.value)} />
          <Textarea label={t('reservations.internal_notes')} autosize minRows={2} value={notes} onChange={(e) => setNotes(e.currentTarget.value)} />
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <SubmitButton loading={save.isPending}>{t('common.save')}</SubmitButton>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

const EVENT_ICONS: Record<string, typeof IconCheck> = {
  created: IconCirclePlus,
  status_changed: IconStatusChange,
  room_assigned: IconBed,
  dates_changed: IconCalendarEvent,
  details_updated: IconPencil,
};

function HistoryTimeline({ events }: { events: ReservationEvent[] }) {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const describe = (e: ReservationEvent): string => {
    const d = e.details as Record<string, unknown>;
    const date = (v: unknown) => formatDate(String(v), i18n.language);
    switch (e.action) {
      case 'created':
        return t('reservations.events.created', { status: t(`reservations.status.${d.status}`), source: t(`reservations.sources.${d.source}`) });
      case 'status_changed':
        return t('reservations.events.status_changed', { from: t(`reservations.status.${d.from}`), to: t(`reservations.status.${d.to}`) }) + (d.reason ? ` — ${d.reason}` : '');
      case 'room_assigned':
        return t('reservations.events.room_assigned', { from: d.old_room ?? t('reservations.unassigned'), to: d.new_room ?? t('reservations.unassigned') });
      case 'dates_changed': {
        const [a, b] = d.old as string[];
        const [c, e2] = d.new as string[];
        return t('reservations.events.dates_changed', { from: `${date(a)} → ${date(b)}`, to: `${date(c)} → ${date(e2)}` });
      }
      case 'details_updated':
        return t('reservations.events.details_updated');
      default:
        return e.action;
    }
  };
  return (
    <Timeline bulletSize={26} lineWidth={2} active={events.length}>
      {[...events].reverse().map((e) => {
        const Icon = EVENT_ICONS[e.action] ?? IconPencil;
        return (
          <Timeline.Item key={e.id} bullet={<Icon size={14} />} title={<Text size="sm" fw={500}>{describe(e)}</Text>}>
            <Text size="xs" c="dimmed">
              {formatDateTime(e.at, i18n.language, hotel.timezone)} · {e.user_name ?? t('audit.system')}
            </Text>
          </Timeline.Item>
        );
      })}
    </Timeline>
  );
}
