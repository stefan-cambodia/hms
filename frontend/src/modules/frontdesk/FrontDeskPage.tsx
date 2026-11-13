import { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { ActionIcon, Anchor, Badge, Button, Card, Group, Loader, SimpleGrid, Table, Tabs, Text, Tooltip } from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import { IconChevronLeft, IconChevronRight, IconDoorEnter, IconDoorExit, IconUserPlus } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { useHotelQuery } from '@/api/hooks';
import type { FrontDesk, StayRow } from '@/api/types';
import { useAuth, useHotel } from '@/auth/AuthProvider';
import { EmptyState, PageHeader } from '@/components/ui';
import { addDays, daysBetween } from '@/lib/dates';
import { formatDate, formatDateTime, formatMoney } from '@/lib/format';
import { NewReservationDrawer } from '@/modules/reservations/NewReservationDrawer';
import { useHotelToday, useInventory } from '@/modules/reservations/shared';
import { useStayActions } from './actions';
import { HousekeepingBadge, RoomBoard } from './RoomBoard';
import { guestsLabel } from '@/lib/guests';

type Tab = 'arrivals' | 'in_house' | 'departures' | 'rooms';
const TABS: Tab[] = ['arrivals', 'in_house', 'departures', 'rooms'];

export default function FrontDeskPage() {
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const navigate = useNavigate();
  const today = useHotelToday();
  const [params, setParams] = useSearchParams();
  const tab = (TABS.includes(params.get('tab') as Tab) ? params.get('tab') : 'arrivals') as Tab;
  const day = /^\d{4}-\d{2}-\d{2}$/.test(params.get('day') ?? '') ? params.get('day')! : today;
  const update = (patch: Record<string, string | null>) =>
    setParams(
      (p) => {
        const out = new URLSearchParams(p);
        for (const [k, v] of Object.entries(patch)) (v === null ? out.delete(k) : out.set(k, v));
        return out;
      },
      { replace: true },
    );
  const desk = useHotelQuery<FrontDesk>('front_desk', '/front-desk', { day: day === today ? undefined : day });
  const actions = useStayActions();
  const [walkIn, setWalkIn] = useState(false);
  const d = desk.data;
  const pendingArrivals = d?.arrivals.filter((r) => !r.checked_in_at).length ?? 0;
  const pendingDepartures = d?.departures.filter((r) => !r.checked_out_at).length ?? 0;

  return (
    <>
      <PageHeader
        title={t('nav.frontdesk')}
        description={t('frontdesk.description')}
        actions={
          <>
            <ActionIcon variant="default" size="lg" aria-label={t('calendar.previous')} onClick={() => update({ day: addDays(day, -1) })}>
              <IconChevronLeft size={18} />
            </ActionIcon>
            <Button variant="default" onClick={() => update({ day: null })}>
              {t('calendar.today')}
            </Button>
            <ActionIcon variant="default" size="lg" aria-label={t('calendar.next')} onClick={() => update({ day: addDays(day, 1) })}>
              <IconChevronRight size={18} />
            </ActionIcon>
            <DatePickerInput value={day} onChange={(v) => v && update({ day: v === today ? null : v })} valueFormat="ddd D MMM YYYY" w={170} aria-label={t('frontdesk.day')} />
            {can('reservations.create') && (
              <Button leftSection={<IconUserPlus size={16} />} onClick={() => setWalkIn(true)}>
                {t('frontdesk.walk_in')}
              </Button>
            )}
          </>
        }
      />
      {d && !d.is_today && (
        <Text size="sm" c="orange.8" mb="sm">
          {t('frontdesk.planning_view', { date: formatDate(day, i18n.language) })}
        </Text>
      )}
      <SimpleGrid cols={{ base: 2, sm: 4 }} mb="md">
        <Stat label={t('frontdesk.tabs.arrivals')} value={d ? `${pendingArrivals} / ${d.arrivals.length}` : '…'} hint={t('frontdesk.to_check_in')} />
        <Stat label={t('frontdesk.tabs.in_house')} value={d ? String(d.in_house.length) : '…'} hint={t('frontdesk.guests_in_house')} />
        <Stat label={t('frontdesk.tabs.departures')} value={d ? `${pendingDepartures} / ${d.departures.length}` : '…'} hint={t('frontdesk.to_check_out')} />
        <Stat label={t('frontdesk.balance_open')} value={d ? String(d.in_house.filter((r) => Number(r.balance) > 0).length) : '…'} hint={t('frontdesk.in_house_owing')} />
      </SimpleGrid>

      <Tabs value={tab} onChange={(v) => v && update({ tab: v === 'arrivals' ? null : v })} keepMounted={false}>
        <Tabs.List mb="md">
          {TABS.map((k) => (
            <Tabs.Tab key={k} value={k} rightSection={k !== 'rooms' && d ? <Badge size="sm" variant="light" circle>{(k === 'arrivals' ? d.arrivals : k === 'departures' ? d.departures : d.in_house).length}</Badge> : undefined}>
              {t(`frontdesk.tabs.${k}`)}
            </Tabs.Tab>
          ))}
          {desk.isFetching && <Loader size="xs" ml="sm" mt={10} />}
        </Tabs.List>
        <Tabs.Panel value="arrivals">
          <StayTable rows={d?.arrivals} mode="arrivals" isToday={!!d?.is_today} actions={actions} />
        </Tabs.Panel>
        <Tabs.Panel value="in_house">
          <StayTable rows={d?.in_house} mode="in_house" isToday={!!d?.is_today} actions={actions} />
        </Tabs.Panel>
        <Tabs.Panel value="departures">
          <StayTable rows={d?.departures} mode="departures" isToday={!!d?.is_today} actions={actions} />
        </Tabs.Panel>
        <Tabs.Panel value="rooms">
          <RoomBoard />
        </Tabs.Panel>
      </Tabs>
      {actions.element}
      <NewReservationDrawer
        opened={walkIn}
        onClose={() => setWalkIn(false)}
        draft={{ arrival: today, departure: addDays(today, 1), source: 'walk_in' }}
        onCreated={(r) => navigate(`/reservations/${r.id}`)}
      />
    </>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <Card padding="sm">
      <Text size="xs" c="dimmed" fw={600}>
        {label}
      </Text>
      <Text size="xl" fw={700} className="hms-num">
        {value}
      </Text>
      <Text size="xs" c="dimmed">
        {hint}
      </Text>
    </Card>
  );
}

function StayTable({ rows, mode, isToday, actions }: { rows?: StayRow[]; mode: 'arrivals' | 'in_house' | 'departures'; isToday: boolean; actions: ReturnType<typeof useStayActions> }) {
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const hotel = useHotel();
  const inv = useInventory();
  if (!rows) return <Loader size="sm" />;
  if (rows.length === 0) return <EmptyState title={t(`frontdesk.empty.${mode}`)} />;
  return (
    <Card padding={0}>
      <div className="hms-table-wrap">
        <Table verticalSpacing="sm" highlightOnHover miw={640}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t('reservations.guest')}</Table.Th>
              <Table.Th>{t('rooms.number')}</Table.Th>
              <Table.Th>{t('frontdesk.stay')}</Table.Th>
              <Table.Th visibleFrom="md">{t('reservations.guests')}</Table.Th>
              <Table.Th ta="right">{t('reservations.balance')}</Table.Th>
              <Table.Th ta="right" />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((r) => (
              <Table.Tr key={r.reservation_room_id} data-stay={r.code}>
                <Table.Td>
                  <Group gap={6} wrap="nowrap">
                    <Anchor component={Link} to={`/reservations/${r.reservation_id}`} fw={600} size="sm">
                      {r.guest_name}
                    </Anchor>
                    {r.vip_level > 0 && (
                      <Badge size="xs" color="brass" variant="light">
                        VIP {r.vip_level}
                      </Badge>
                    )}
                    {r.flags.map((f) => (
                      <Badge key={f} size="xs" color={f === 'overdue' ? 'red' : 'orange'} variant="light">
                        {t(`frontdesk.flags.${f}`)}
                      </Badge>
                    ))}
                  </Group>
                  <Text size="xs" c="dimmed">
                    {r.code}
                    {r.special_requests ? ` · ${r.special_requests}` : ''}
                  </Text>
                </Table.Td>
                <Table.Td>
                  {r.room_number ? (
                    <Group gap={6} wrap="nowrap">
                      <Text fw={600} className="hms-num">
                        {r.room_number}
                      </Text>
                      {r.housekeeping_status && mode === 'arrivals' && !r.checked_in_at && <HousekeepingBadge status={r.housekeeping_status} />}
                    </Group>
                  ) : (
                    <Badge color="orange" variant="light" radius="sm">
                      {t('reservations.unassigned')}
                    </Badge>
                  )}
                  <Text size="xs" c="dimmed">
                    {inv.typeName(r.room_type_id)}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm">
                    {formatDate(r.arrival, i18n.language)} → {formatDate(r.departure, i18n.language)}
                  </Text>
                  <Text size="xs" c="dimmed">
                    {t('reservations.nights', { count: daysBetween(r.arrival, r.departure) })}
                    {r.checked_in_at ? ` · ${t('frontdesk.in_since', { time: formatDateTime(r.checked_in_at, i18n.language, hotel.timezone) })}` : ''}
                  </Text>
                </Table.Td>
                <Table.Td visibleFrom="md">
                  <Text size="sm">{guestsLabel(t, r.adults, r.children)}</Text>
                </Table.Td>
                <Table.Td ta="right" className="hms-num">
                  <Text size="sm" fw={600} c={Number(r.balance) > 0 ? 'red.7' : Number(r.balance) < 0 ? 'orange.7' : 'teal.7'}>
                    {formatMoney(r.balance, r.currency, i18n.language)}
                  </Text>
                </Table.Td>
                <Table.Td ta="right">
                  <RowAction row={r} mode={mode} isToday={isToday} actions={actions} canIn={can('frontdesk.checkin')} canOut={can('frontdesk.checkout')} />
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </div>
    </Card>
  );
}

function RowAction({
  row: r,
  mode,
  isToday,
  actions,
  canIn,
  canOut,
}: {
  row: StayRow;
  mode: 'arrivals' | 'in_house' | 'departures';
  isToday: boolean;
  actions: ReturnType<typeof useStayActions>;
  canIn: boolean;
  canOut: boolean;
}) {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  if (mode === 'arrivals') {
    if (r.checked_in_at)
      return (
        <Badge color="teal" variant="light">
          {t('frontdesk.checked_in_at', { time: formatDateTime(r.checked_in_at, i18n.language, hotel.timezone) })}
        </Badge>
      );
    if (!isToday || !canIn) return null;
    if (!r.room_id)
      return (
        <Button component={Link} to={`/reservations/${r.reservation_id}`} size="xs" variant="light" color="orange">
          {t('frontdesk.assign_room')}
        </Button>
      );
    return (
      <Button size="xs" leftSection={<IconDoorEnter size={14} />} loading={actions.busy} onClick={() => void actions.checkIn(r.reservation_id, r.version, { reservation_room_ids: [r.reservation_room_id] })}>
        {t('frontdesk.check_in')}
      </Button>
    );
  }
  if (r.checked_out_at)
    return (
      <Badge color="gray" variant="light">
        {t('frontdesk.checked_out_at', { time: formatDateTime(r.checked_out_at, i18n.language, hotel.timezone) })}
      </Badge>
    );
  if (!isToday || !canOut) return null;
  return (
    <Tooltip label={t('frontdesk.check_out_hint')} disabled={mode !== 'in_house'}>
      <Button
        size="xs"
        variant={mode === 'departures' ? 'filled' : 'light'}
        leftSection={<IconDoorExit size={14} />}
        loading={actions.busy}
        onClick={() => void actions.checkOut(r.reservation_id, r.version, { reservation_room_ids: [r.reservation_room_id] })}
      >
        {t('frontdesk.check_out')}
      </Button>
    </Tooltip>
  );
}
