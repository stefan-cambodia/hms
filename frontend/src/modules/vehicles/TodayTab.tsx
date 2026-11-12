import { Card, Group, Loader, SimpleGrid, Stack, Table, Text, Title } from '@mantine/core';
import { useTranslation } from 'react-i18next';

import { useHotelQuery } from '@/api/hooks';
import type { Rental } from '@/api/types';
import { useHotel } from '@/auth/AuthProvider';
import { EmptyState } from '@/components/ui';
import { isoToHotelLocal } from '@/lib/dates';
import { formatDateTime, formatMoney } from '@/lib/format';
import { useHotelToday } from '@/modules/reservations/shared';
import type { RentalActions } from './VehiclesPage';
import { RentalStatusBadge } from './shared';

/** Today's work: vehicles to hand over, out on the road, due back, coming next. */
export default function TodayTab({ actions }: { actions: RentalActions }) {
  const { t } = useTranslation();
  const hotel = useHotel();
  const today = useHotelToday();
  const list = useHotelQuery<Rental[]>('vehicle_rental', '/vehicle-rentals', { status: 'active' });
  if (list.isPending) return <Loader size="sm" />;
  const day = (iso: string) => isoToHotelLocal(iso, hotel.timezone).slice(0, 10);
  const rows = list.data ?? [];
  const toHandOver = rows.filter((r) => r.status === 'reserved' && day(r.start_at) <= today);
  const out = rows.filter((r) => r.status === 'out');
  const dueBack = out.filter((r) => day(r.end_at) <= today);
  const upcoming = rows.filter((r) => r.status === 'reserved' && day(r.start_at) > today);
  if (rows.length === 0) return <EmptyState title={t('vehicles.nothing_active')} description={t('vehicles.nothing_active_hint')} />;
  return (
    <Stack>
      <SimpleGrid cols={{ base: 2, md: 4 }}>
        <Stat label={t('vehicles.to_hand_over')} value={toHandOver.length} />
        <Stat label={t('vehicles.out_now')} value={out.length} />
        <Stat label={t('vehicles.due_back')} value={dueBack.length} />
        <Stat label={t('vehicles.upcoming')} value={upcoming.length} />
      </SimpleGrid>
      <Section title={t('vehicles.to_hand_over')} rows={toHandOver} actions={actions} />
      <Section title={t('vehicles.out_now')} rows={out} actions={actions} />
      <Section title={t('vehicles.upcoming')} rows={upcoming} actions={actions} />
    </Stack>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <Card padding="sm">
      <Text size="xs" c="dimmed" fw={600}>
        {label}
      </Text>
      <Text size="xl" fw={700}>
        {value}
      </Text>
    </Card>
  );
}

function Section({ title, rows, actions }: { title: string; rows: Rental[]; actions: RentalActions }) {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  if (rows.length === 0) return null;
  return (
    <Card padding={0}>
      <Title order={5} p="sm">
        {title}
      </Title>
      <div className="hms-table-wrap">
        <Table highlightOnHover verticalSpacing="sm" miw={640}>
          <Table.Tbody>
            {rows.map((r) => (
              <Table.Tr key={r.id} style={{ cursor: 'pointer' }} onClick={() => actions.open(r.id)} data-rental={r.number}>
                <Table.Td>
                  <Text size="sm" fw={600}>
                    {r.vehicle_label}
                  </Text>
                  <Text size="xs" c="dimmed">
                    {r.number} · {t(`vehicles.kinds.${r.vehicle_kind}`)}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{r.guest_name}</Text>
                  {r.room_number && (
                    <Text size="xs" c="dimmed">
                      {t('restaurant.room_n', { number: r.room_number })}
                    </Text>
                  )}
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{formatDateTime(r.start_at, i18n.language, hotel.timezone)}</Text>
                  <Text size="xs" c="dimmed">
                    → {formatDateTime(r.end_at, i18n.language, hotel.timezone)}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Group gap={6}>
                    <RentalStatusBadge status={r.status} overdue={r.overdue} />
                  </Group>
                </Table.Td>
                <Table.Td ta="right" className="hms-num">
                  <Text size="sm" fw={600} c={Number(r.balance) > 0 ? 'red.7' : 'teal.7'}>
                    {formatMoney(r.balance, hotel.currency_code, i18n.language)}
                  </Text>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </div>
    </Card>
  );
}
