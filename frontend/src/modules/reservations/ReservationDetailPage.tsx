import { useState } from 'react';
import { Link, useParams } from 'react-router';
import {
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Checkbox,
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
  IconArrowsExchange,
  IconBed,
  IconCash,
  IconDoorEnter,
  IconDoorExit,
  IconFileInvoice,
  IconReceipt,
  IconCalendarEvent,
  IconCheck,
  IconChevronDown,
  IconCirclePlus,
  IconEdit,
  IconPencil,
  IconCurrencyDollar,
  IconStatusChange,
  IconX,
} from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { api } from '@/api/client';
import { useHotelMutation, useHotelQuery } from '@/api/hooks';
import { ApiError } from '@/api/client';
import type { AvailableRoom, FeePreview, Offer, Reservation, ReservationEvent, ReservationRoom, ReservationSource } from '@/api/types';
import { PageLoader } from '@/app/AppLayout';
import { useAuth, useHotel } from '@/auth/AuthProvider';
import { EmptyState, SubmitButton } from '@/components/ui';
import { daysBetween } from '@/lib/dates';
import { errorMessage, notifyError, notifySuccess } from '@/lib/errors';
import { countryName, formatDate, formatDateTime, formatMoney } from '@/lib/format';
import { pickLocalized } from '@/lib/localized';
import { issueLabel, policySummary, usePricingLookups } from '@/modules/pricing/shared';
import { addDays } from '@/lib/dates';
import { FolioSection } from '@/modules/billing/FolioSection';
import { useStayActions } from '@/modules/frontdesk/actions';
import { FlagBadges, SOURCES, StatusBadge, useHotelToday, useInventory } from './shared';

const INVALIDATES = ['reservation', 'calendar', 'folio', 'front_desk', 'room_board'];

export default function ReservationDetailPage() {
  const { id } = useParams();
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const { can } = useAuth();
  const today = useHotelToday();
  const res = useHotelQuery<Reservation>('reservation', `/reservations/${id}`);
  const history = useHotelQuery<ReservationEvent[]>('reservation', `/reservations/${id}/events`);
  const [cancelling, setCancelling] = useState<'cancel' | 'no_show' | null>(null);
  const [editing, setEditing] = useState(false);
  const stayActions = useStayActions();

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
  const waiting = r.rooms.filter((rr) => rr.occupies_inventory && !rr.checked_in_at && rr.arrival <= today && today < rr.departure);
  const inHouse = r.rooms.filter((rr) => rr.checked_in_at && !rr.checked_out_at);
  const canCheckIn = can('frontdesk.checkin') && (open || r.status === 'checked_in') && waiting.length > 0;
  const canCheckOut = can('frontdesk.checkout') && r.status === 'checked_in' && inHouse.length > 0;

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
          {canCheckIn && (
            <Button
              color="teal"
              leftSection={<IconDoorEnter size={16} />}
              loading={stayActions.busy}
              disabled={waiting.some((rr) => !rr.room_id)}
              title={waiting.some((rr) => !rr.room_id) ? t('frontdesk.assign_room_first') : undefined}
              onClick={() => void stayActions.checkIn(r.id, r.version)}
            >
              {t('frontdesk.check_in')}
            </Button>
          )}
          {canCheckOut && (
            <Button leftSection={<IconDoorExit size={16} />} loading={stayActions.busy} onClick={() => void stayActions.checkOut(r.id, r.version)}>
              {t('frontdesk.check_out')}
            </Button>
          )}
          {can('reservations.edit') && r.status === 'pending' && (
            <Button leftSection={<IconCheck size={16} />} loading={action.isPending} onClick={() => run('confirm', {}, t('reservations.confirmed_done'))}>
              {t('reservations.actions.confirm')}
            </Button>
          )}
          {can('reservations.edit') && open && r.arrival <= today && (
            <Button variant="default" onClick={() => setCancelling('no_show')}>
              {t('reservations.actions.no_show')}
            </Button>
          )}
          {can('reservations.edit') && r.status !== 'cancelled' && (
            <Button variant="default" leftSection={<IconEdit size={16} />} onClick={() => setEditing(true)}>
              {t('reservations.actions.edit')}
            </Button>
          )}
          {can('reservations.cancel') && open && (
            <Button variant="light" color="red" leftSection={<IconX size={16} />} onClick={() => setCancelling('cancel')}>
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
              <StayCard key={rr.id} reservation={r} stay={rr} index={i} editable={canEdit} onUndoCheckIn={() => void stayActions.undoCheckIn(r, rr.id)} />
            ))}
            {can('payments.view') && <FolioSection reservation={r} />}
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
              <HistoryTimeline events={history.data ?? []} currency={r.currency} />
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
                {Number(r.charges_total) !== 0 && <Row label={t('billing.extras')} value={formatMoney(r.charges_total, r.currency, i18n.language)} />}
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
                <Row strong label={Number(r.balance) < 0 ? t('billing.credit') : t('reservations.balance')} value={formatMoney(Math.abs(Number(r.balance)), r.currency, i18n.language)} />
              </Stack>
            </Card>
          </Stack>
        </Grid.Col>
      </Grid>

      {cancelling && (
        <CancelModal
          reservation={r}
          mode={cancelling}
          onClose={() => setCancelling(null)}
          onConfirm={(body) =>
            run(cancelling === 'cancel' ? 'cancel' : 'no-show', body, cancelling === 'cancel' ? t('reservations.cancelled_done') : t('reservations.no_show_done')).then(() => setCancelling(null))
          }
          loading={action.isPending}
        />
      )}
      {stayActions.element}
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

function StayCard({
  reservation: r,
  stay,
  index,
  editable,
  onUndoCheckIn,
}: {
  reservation: Reservation;
  stay: ReservationRoom;
  index: number;
  editable: boolean;
  onUndoCheckIn: () => void;
}) {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const inv = useInventory();
  const [showNights, setShowNights] = useState(false);
  const [changingDates, setChangingDates] = useState(false);
  const [moving, setMoving] = useState(false);
  const inHouse = !!stay.checked_in_at && !stay.checked_out_at;
  const live = stay.occupies_inventory;
  const free = useHotelQuery<AvailableRoom[]>(
    'calendar',
    '/available-rooms',
    { start: stay.arrival, end: stay.departure, room_type_id: stay.room_type_id, ignore_reservation_room: stay.id },
    editable && live && !stay.checked_in_at,
  );
  const { can } = useAuth();
  const hotelDay = useHotelToday();
  const pricing = usePricingLookups();
  const plan = stay.rate_plan_id ? pricing.planById.get(stay.rate_plan_id) : pricing.defaultPlan;
  const policy = plan?.cancellation_policy_id ? pricing.policyById.get(plan.cancellation_policy_id) : undefined;
  const freeUntil = plan?.is_refundable && policy?.free_until_days !== null && policy?.free_until_days !== undefined ? addDays(stay.arrival, -policy.free_until_days) : null;
  const offers = useHotelQuery<Offer[]>(
    'rate',
    '/rates/offers',
    { arrival: stay.arrival, departure: stay.departure, adults: stay.adults, children: stay.children, room_type_id: stay.room_type_id },
    editable && live,
  );
  const changeRate = useHotelMutation<{ planId: string; override: boolean }, Reservation>(
    (h, { planId, override }) =>
      api.post<Reservation>(h(`/reservations/${r.id}/rooms/${stay.id}/rate-plan`), { version: r.version, rate_plan_id: planId, override_restrictions: override }),
    INVALIDATES,
  );
  const onRateChange = (planId: string | null) => {
    if (!planId || planId === stay.rate_plan_id) return;
    const offer = offers.data?.find((o) => o.rate_plan_id === planId);
    const confirmChange = (override: boolean) =>
      changeRate.mutateAsync({ planId, override }).then(() => notifySuccess(t('reservations.rate_saved')), (err) => {
        if (err instanceof ApiError && err.status === 409 && !override && can('reservations.override_restrictions') && !['VERSION_CONFLICT', 'RESERVATION_CLOSED'].includes(err.code)) {
          modals.openConfirmModal({
            title: t('reservations.form.restricted_title'),
            children: <Text size="sm">{errorMessage(err)}</Text>,
            labels: { confirm: t('reservations.form.override_restrictions'), cancel: t('common.cancel') },
            onConfirm: () => void confirmChange(true),
          });
        } else notifyError(err);
      });
    modals.openConfirmModal({
      title: t('reservations.change_rate_title'),
      children: (
        <Text size="sm">
          {t('reservations.change_rate_body', {
            plan: pricing.planName(planId),
            old: formatMoney(stay.accommodation_total, r.currency, i18n.language),
            new: offer ? formatMoney(offer.total, r.currency, i18n.language) : '—',
          })}
        </Text>
      ),
      labels: { confirm: t('common.save'), cancel: t('common.cancel') },
      onConfirm: () => void confirmChange(false),
    });
  };
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
          {editable && live && !stay.checked_out_at && (
            <Button variant="default" leftSection={<IconCalendarEvent size={16} />} onClick={() => setChangingDates(true)}>
              {t('reservations.actions.change_dates')}
            </Button>
          )}
        </Group>
      </Group>
      {stay.checked_in_at && (
        <Group gap={6} mt="xs" wrap="wrap">
          <Badge color={inHouse ? 'teal' : 'gray'} variant="light" radius="sm">
            {inHouse
              ? t('frontdesk.checked_in_at', { time: formatDateTime(stay.checked_in_at, i18n.language, hotel.timezone) })
              : t('frontdesk.checked_out_at', { time: formatDateTime(stay.checked_out_at, i18n.language, hotel.timezone) })}
          </Badge>
          {inHouse && can('frontdesk.checkin') && (
            <Button size="xs" variant="default" leftSection={<IconArrowsExchange size={14} />} onClick={() => setMoving(true)}>
              {t('frontdesk.move_room')}
            </Button>
          )}
          {inHouse && can('frontdesk.checkin') && localDate(stay.checked_in_at, hotel.timezone) === hotelDay && (
            <Button size="xs" variant="subtle" color="gray" onClick={onUndoCheckIn}>
              {t('frontdesk.undo_check_in')}
            </Button>
          )}
        </Group>
      )}
      <Group mt="sm" gap="sm" wrap="wrap" align="flex-end">
        {editable && live && !stay.checked_out_at ? (
          <Select
            label={t('reservations.rate')}
            w={300}
            data={(offers.data ?? []).map((o) => ({
              value: o.rate_plan_id,
              label: `${pricing.planName(o.rate_plan_id)} · ${formatMoney(o.total, r.currency, i18n.language)}`,
            }))}
            value={stay.rate_plan_id}
            onChange={onRateChange}
            allowDeselect={false}
            disabled={changeRate.isPending}
          />
        ) : (
          <Text size="sm">
            {t('reservations.rate')}: <b>{pricing.planName(stay.rate_plan_id)}</b>
          </Text>
        )}
        <div>
          <Text size="xs" c="dimmed">
            {plan ? t(`pricing.meal_plans.${plan.meal_plan}`) : ''} ·{' '}
            {plan && !plan.is_refundable ? t('pricing.plans.non_refundable') : policySummary(policy, t)}
          </Text>
          {freeUntil && (
            <Text size="xs" c={freeUntil < hotelDay ? 'dimmed' : 'teal.7'}>
              {t('reservations.free_cancellation_until', { date: formatDate(freeUntil, i18n.language) })}
            </Text>
          )}
        </div>
      </Group>
      {offers.data && (() => {
        const current = offers.data.find((o) => o.rate_plan_id === stay.rate_plan_id);
        return current && current.issues.length > 0 && editable ? (
          <Text size="xs" c="dimmed" mt={4}>
            {t('reservations.current_restrictions')}: {current.issues.map((x) => issueLabel(x, t, i18n.language)).join(' · ')}
          </Text>
        ) : null;
      })()}
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
      {moving && <MoveRoomModal reservation={r} stay={stay} onClose={() => setMoving(false)} />}
    </Card>
  );
}

/** Calendar date of an instant in the hotel's time zone (YYYY-MM-DD). */
function localDate(iso: string | null, timeZone: string): string | null {
  if (!iso) return null;
  return new Intl.DateTimeFormat('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(iso));
}

function MoveRoomModal({ reservation: r, stay, onClose }: { reservation: Reservation; stay: ReservationRoom; onClose: () => void }) {
  const { t, i18n } = useTranslation();
  const inv = useInventory();
  const today = useHotelToday();
  const start = today > stay.arrival ? today : stay.arrival;
  const free = useHotelQuery<AvailableRoom[]>('calendar', '/available-rooms', { start, end: stay.departure });
  const [roomId, setRoomId] = useState<string | null>(null);
  const [reason, setReason] = useState('');
  const [notReady, setNotReady] = useState<string | null>(null);
  const move = useHotelMutation<boolean, Reservation>(
    (h, ignore) =>
      api.post<Reservation>(h(`/reservations/${r.id}/rooms/${stay.id}/room-move`), {
        version: r.version,
        room_id: roomId,
        reason: reason.trim() || undefined,
        ignore_room_status: ignore,
      }),
    INVALIDATES,
  );
  const submit = (ignore: boolean) =>
    move.mutateAsync(ignore).then(
      () => {
        notifySuccess(t('frontdesk.moved_done'));
        onClose();
      },
      (err) => {
        if (err instanceof ApiError && err.code === 'ROOM_NOT_READY' && !ignore) setNotReady(errorMessage(err));
        else notifyError(err);
      },
    );
  return (
    <Modal opened onClose={onClose} title={t('frontdesk.move_room')}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (roomId) void submit(!!notReady);
        }}
      >
        <Stack>
          <Text size="sm">{t('frontdesk.move_room_body', { date: formatDate(start, i18n.language) })}</Text>
          <Select
            label={t('frontdesk.new_room')}
            searchable
            data={(free.data ?? []).map((room) => ({ value: room.id, label: `${room.number} · ${inv.typeName(room.room_type_id)}` }))}
            value={roomId}
            onChange={(v) => {
              setRoomId(v);
              setNotReady(null);
            }}
            nothingFoundMessage={t('frontdesk.no_free_room')}
          />
          <TextInput label={t('frontdesk.move_reason')} maxLength={300} value={reason} onChange={(e) => setReason(e.currentTarget.value)} />
          {notReady && (
            <Alert color="orange" p="sm">
              <Text size="sm">
                {notReady} {t('frontdesk.room_not_ready_body')}
              </Text>
            </Alert>
          )}
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <SubmitButton loading={move.isPending} disabled={!roomId}>
              {notReady ? t('frontdesk.move_anyway') : t('frontdesk.move_room')}
            </SubmitButton>
          </Group>
        </Stack>
      </form>
    </Modal>
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

function CancelModal({
  reservation: r,
  mode,
  onClose,
  onConfirm,
  loading,
}: {
  reservation: Reservation;
  mode: 'cancel' | 'no_show';
  onClose: () => void;
  onConfirm: (body: Record<string, unknown>) => void;
  loading: boolean;
}) {
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const [reason, setReason] = useState('');
  const [waive, setWaive] = useState(false);
  const preview = useHotelQuery<FeePreview>('reservation', `/reservations/${r.id}/fee-preview`, { action: mode });
  const fee = Number(preview.data?.fee ?? 0);
  const needsReason = mode === 'cancel';
  return (
    <Modal opened onClose={onClose} title={mode === 'cancel' ? t('reservations.actions.cancel') : t('reservations.actions.no_show')}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (needsReason && !reason.trim()) return;
          onConfirm({ ...(needsReason ? { reason: reason.trim() } : {}), waive_fee: waive });
        }}
      >
        <Stack>
          <Text size="sm">{mode === 'cancel' ? t('reservations.cancel_body') : t('reservations.no_show_body')}</Text>
          {preview.data && (
            <Alert color={fee > 0 ? 'orange' : 'teal'} p="sm" data-testid="fee-preview">
              <Text size="sm">
                {fee > 0
                  ? t(mode === 'cancel' ? 'billing.cancellation_fee_due' : 'billing.no_show_fee_due', { amount: formatMoney(fee, r.currency, i18n.language) })
                  : t(mode === 'cancel' ? 'billing.cancellation_free' : 'billing.no_show_free')}
              </Text>
              {preview.data.stays
                .filter((s) => s.free_until)
                .map((s) => (
                  <Text key={s.reservation_room_id} size="xs" c="dimmed">
                    {t('reservations.free_cancellation_until', { date: formatDate(s.free_until, i18n.language) })}
                  </Text>
                ))}
            </Alert>
          )}
          {fee > 0 && can('folio.adjust') && <Checkbox label={t('billing.waive_fee')} checked={waive} onChange={(e) => setWaive(e.currentTarget.checked)} />}
          {needsReason && (
            <Textarea label={t('reservations.cancel_reason')} required autosize minRows={2} value={reason} onChange={(e) => setReason(e.currentTarget.value)} data-autofocus />
          )}
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <SubmitButton color="red" loading={loading} disabled={(needsReason && !reason.trim()) || preview.isPending}>
              {mode === 'cancel' ? t('reservations.actions.cancel') : t('reservations.actions.no_show')}
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
  rate_plan_changed: IconCurrencyDollar,
  dates_changed: IconCalendarEvent,
  details_updated: IconPencil,
  checked_in: IconDoorEnter,
  check_in_undone: IconDoorEnter,
  checked_out: IconDoorExit,
  room_moved: IconArrowsExchange,
  charge_posted: IconReceipt,
  charge_voided: IconReceipt,
  payment_recorded: IconCash,
  payment_voided: IconCash,
  invoice_issued: IconFileInvoice,
  invoice_voided: IconFileInvoice,
};

function HistoryTimeline({ events, currency }: { events: ReservationEvent[]; currency: string }) {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const money = (v: unknown, cur = currency) => formatMoney(String(v), cur, i18n.language);
  const describe = (e: ReservationEvent): string => {
    const d = e.details as Record<string, unknown>;
    const date = (v: unknown) => formatDate(String(v), i18n.language);
    switch (e.action) {
      case 'created':
        return t('reservations.events.created', { status: t(`reservations.status.${d.status}`), source: t(`reservations.sources.${d.source}`) });
      case 'status_changed': {
        let text = t('reservations.events.status_changed', { from: t(`reservations.status.${d.from}`), to: t(`reservations.status.${d.to}`) }) + (d.reason ? ` — ${d.reason}` : '');
        if (d.fee && Number(d.fee) > 0) text += ` · ${d.fee_waived ? t('reservations.events.fee_waived', { amount: money(d.fee) }) : t('reservations.events.fee_charged', { amount: money(d.fee) })}`;
        return text;
      }
      case 'checked_in':
        return t('reservations.events.checked_in', { rooms: (d.rooms as string[]).join(', ') }) + ((d.room_not_ready as string[] | undefined)?.length ? ` · ${t('reservations.events.room_not_ready')}` : '');
      case 'check_in_undone':
        return t('reservations.events.check_in_undone', { room: d.room ?? '—' });
      case 'checked_out': {
        let text = t('reservations.events.checked_out', { rooms: (d.rooms as string[]).join(', ') });
        const early = Object.values((d.early_departure ?? {}) as Record<string, { nights: number }>);
        if (early.length) text += ` · ${t('reservations.events.early_departure', { count: early.reduce((n, x) => n + x.nights, 0) })}`;
        if (d.open_balance) text += ` · ${t('reservations.events.open_balance', { amount: money(d.open_balance) })}`;
        return text;
      }
      case 'room_moved':
        return t('reservations.events.room_moved', { from: d.old_room ?? '—', to: d.new_room }) + (d.reason ? ` — ${d.reason}` : '');
      case 'charge_posted': {
        const name =
          d.kind === 'fee'
            ? t(`billing.fee_types.${d.fee_type ?? 'other'}`)
            : d.kind === 'adjustment'
              ? `${t('billing.adjustment')}${d.description ? ` (${d.description})` : ''}`
              : pickLocalized(d.name as Record<string, string>, i18n.language, hotel.default_language) || String(d.description ?? '');
        return t(d.automatic ? 'reservations.events.charge_posted_auto' : 'reservations.events.charge_posted', { name, amount: money(d.amount) });
      }
      case 'charge_voided':
        return t('reservations.events.charge_voided', { amount: money(d.amount), reason: d.reason });
      case 'payment_recorded':
        return t('reservations.events.payment_recorded', {
          number: d.number,
          kind: t(`billing.payment_kinds.${d.kind}`),
          method: t(`billing.methods.${d.method}`),
          amount: money(d.amount, String(d.currency)),
        });
      case 'payment_voided':
        return t('reservations.events.payment_voided', { number: d.number, reason: d.reason });
      case 'invoice_issued':
        return t('reservations.events.invoice_issued', { number: d.number, amount: money(d.total) });
      case 'invoice_voided':
        return t('reservations.events.invoice_voided', { number: d.number, reason: d.reason });
      case 'room_assigned':
        return t('reservations.events.room_assigned', { from: d.old_room ?? t('reservations.unassigned'), to: d.new_room ?? t('reservations.unassigned') });
      case 'dates_changed': {
        const [a, b] = d.old as string[];
        const [c, e2] = d.new as string[];
        return t('reservations.events.dates_changed', { from: `${date(a)} → ${date(b)}`, to: `${date(c)} → ${date(e2)}` });
      }
      case 'details_updated':
        return t('reservations.events.details_updated');
      case 'rate_plan_changed':
        return t('reservations.events.rate_plan_changed', { from: d.old ?? '—', to: d.new ?? '—' });
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
