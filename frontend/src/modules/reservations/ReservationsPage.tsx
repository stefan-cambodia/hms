import { useState } from 'react';
import { useNavigate } from 'react-router';
import { Badge, Button, Card, Group, Pagination, SegmentedControl, Select, Table, Text, TextInput } from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { IconPlus, IconSearch } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { useHotelQuery } from '@/api/hooks';
import type { Page, ReservationListItem } from '@/api/types';
import { useAuth } from '@/auth/AuthProvider';
import { EmptyState, PageHeader } from '@/components/ui';
import { daysBetween } from '@/lib/dates';
import { formatDate, formatMoney } from '@/lib/format';
import { NewReservationDrawer } from './NewReservationDrawer';
import { FlagBadges, STATUSES, StatusBadge, useHotelToday } from './shared';

const PAGE = 50;
type Quick = 'all' | 'arrivals' | 'departures' | 'in_house' | 'pending';

export default function ReservationsPage() {
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const navigate = useNavigate();
  const today = useHotelToday();
  const [quick, setQuick] = useState<Quick>('all');
  const [status, setStatus] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [q] = useDebouncedValue(search, 250);
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);

  const params = {
    q,
    status: quick === 'in_house' ? 'checked_in' : quick === 'pending' ? 'pending' : status,
    arrival: quick === 'arrivals' ? today : undefined,
    departure: quick === 'departures' ? today : undefined,
    limit: PAGE,
    offset: (page - 1) * PAGE,
  };
  const list = useHotelQuery<Page<ReservationListItem>>('reservation', '/reservations', params);
  const total = list.data?.total ?? 0;

  return (
    <>
      <PageHeader
        title={t('nav.reservations')}
        description={t('reservations.description')}
        actions={
          can('reservations.create') && (
            <Button leftSection={<IconPlus size={16} />} onClick={() => setCreating(true)}>
              {t('reservations.new')}
            </Button>
          )
        }
      />
      <Card mb="md" padding="md">
        <Group gap="sm" wrap="wrap">
          <SegmentedControl
            value={quick}
            onChange={(v) => {
              setQuick(v as Quick);
              setPage(1);
            }}
            data={(['all', 'arrivals', 'departures', 'in_house', 'pending'] as const).map((k) => ({ value: k, label: t(`reservations.quick.${k}`) }))}
          />
          <TextInput
            placeholder={t('reservations.search')}
            leftSection={<IconSearch size={16} />}
            value={search}
            onChange={(e) => {
              setSearch(e.currentTarget.value);
              setPage(1);
            }}
            w={{ base: '100%', sm: 260 }}
          />
          {quick === 'all' && (
            <Select
              placeholder={t('reservations.all_statuses')}
              clearable
              data={STATUSES.map((s) => ({ value: s, label: t(`reservations.status.${s}`) }))}
              value={status}
              onChange={(v) => {
                setStatus(v);
                setPage(1);
              }}
              w={{ base: '100%', sm: 180 }}
            />
          )}
        </Group>
      </Card>

      {list.isSuccess && total === 0 ? (
        <EmptyState title={t('reservations.empty')} description={q ? undefined : t('reservations.empty_hint')} />
      ) : (
        <Card padding={0}>
          <div className="hms-table-wrap">
            <Table miw={640} highlightOnHover>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t('reservations.code')}</Table.Th>
                  <Table.Th>{t('reservations.guest')}</Table.Th>
                  <Table.Th>{t('reservations.stay')}</Table.Th>
                  <Table.Th visibleFrom="sm">{t('reservations.rooms')}</Table.Th>
                  <Table.Th visibleFrom="md">{t('reservations.source')}</Table.Th>
                  <Table.Th>{t('common.status')}</Table.Th>
                  <Table.Th ta="right" visibleFrom="sm">
                    {t('reservations.total')}
                  </Table.Th>
                  <Table.Th ta="right" visibleFrom="lg">
                    {t('reservations.balance')}
                  </Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {list.data?.items.map((r) => (
                  <Table.Tr key={r.id} onClick={() => navigate(`/reservations/${r.id}`)} style={{ cursor: 'pointer' }}>
                    <Table.Td>
                      <Text fw={650} size="sm" className="hms-num">
                        {r.code}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm" fw={500}>
                        {r.guest_name}
                      </Text>
                      <Text size="xs" c="dimmed">
                        {t('reservations.guests_count', { adults: r.adults, children: r.children })}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm" style={{ whiteSpace: 'nowrap' }}>
                        {formatDate(r.arrival, i18n.language)} → {formatDate(r.departure, i18n.language)}
                      </Text>
                      <Text size="xs" c="dimmed">
                        {t('reservations.nights', { count: daysBetween(r.arrival, r.departure) })}
                      </Text>
                    </Table.Td>
                    <Table.Td visibleFrom="sm">
                      {r.room_numbers.length ? (
                        <Text size="sm" className="hms-num">
                          {r.room_numbers.join(', ')}
                        </Text>
                      ) : null}
                      {r.room_numbers.length < r.room_count && (
                        <Badge size="sm" color="orange" variant="light" radius="sm">
                          {t('reservations.unassigned_n', { count: r.room_count - r.room_numbers.length })}
                        </Badge>
                      )}
                    </Table.Td>
                    <Table.Td visibleFrom="md">
                      <Text size="sm">{t(`reservations.sources.${r.source}`)}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Group gap={4} wrap="nowrap">
                        <StatusBadge status={r.status} />
                        <FlagBadges overbooked={r.is_overbooked} />
                      </Group>
                    </Table.Td>
                    <Table.Td ta="right" className="hms-num" visibleFrom="sm">
                      {formatMoney(r.grand_total, r.currency, i18n.language)}
                    </Table.Td>
                    <Table.Td ta="right" className="hms-num" visibleFrom="lg">
                      <Text size="sm" c={Number(r.balance) > 0 ? undefined : 'dimmed'}>
                        {formatMoney(r.balance, r.currency, i18n.language)}
                      </Text>
                    </Table.Td>
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
      <NewReservationDrawer opened={creating} onClose={() => setCreating(false)} onCreated={(r) => navigate(`/reservations/${r.id}`)} />
    </>
  );
}
