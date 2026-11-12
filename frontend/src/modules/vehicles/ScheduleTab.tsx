import { useMemo, useState } from 'react';
import { ActionIcon, Box, Button, Card, Group, Text, Tooltip } from '@mantine/core';
import { IconChevronLeft, IconChevronRight } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { useHotelQuery } from '@/api/hooks';
import type { Rental, Vehicle } from '@/api/types';
import { useAuth, useHotel } from '@/auth/AuthProvider';
import { EmptyState } from '@/components/ui';
import { addDays, dayLabel, hotelLocalToIso, weekday } from '@/lib/dates';
import { useHotelToday } from '@/modules/reservations/shared';
import type { RentalActions } from './VehiclesPage';

const DAYS = 14;
const COLORS: Record<string, string> = { reserved: 'blue', out: 'orange', returned: 'teal' };

/** Vehicles × days: who has which vehicle when. */
export default function ScheduleTab({ actions }: { actions: RentalActions }) {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const { can } = useAuth();
  const today = useHotelToday();
  const [start, setStart] = useState(today);
  const days = useMemo(() => Array.from({ length: DAYS }, (_, i) => addDays(start, i)), [start]);
  const from = hotelLocalToIso(`${start} 00:00`, hotel.timezone);
  const to = hotelLocalToIso(`${addDays(start, DAYS)} 00:00`, hotel.timezone);
  const fleet = useHotelQuery<Vehicle[]>('vehicle', '/vehicles');
  const rentals = useHotelQuery<Rental[]>('vehicle_rental', '/vehicle-rentals', { start: from, end: to });
  const vehicles = (fleet.data ?? []).filter((v) => v.status !== 'retired');
  const active = (rentals.data ?? []).filter((r) => r.status !== 'cancelled' && r.status !== 'no_show');
  const bounds = useMemo(() => days.map((d) => [hotelLocalToIso(`${d} 00:00`, hotel.timezone), hotelLocalToIso(`${addDays(d, 1)} 00:00`, hotel.timezone)]), [days, hotel.timezone]);
  if (fleet.data && vehicles.length === 0) return <EmptyState title={t('vehicles.no_fleet')} />;
  const W = 72;
  return (
    <Card padding={0}>
      <Group p="sm" gap="xs">
        <ActionIcon variant="default" size="lg" aria-label={t('calendar.previous')} onClick={() => setStart(addDays(start, -7))}>
          <IconChevronLeft size={18} />
        </ActionIcon>
        <Button variant="default" onClick={() => setStart(today)}>
          {t('calendar.today')}
        </Button>
        <ActionIcon variant="default" size="lg" aria-label={t('calendar.next')} onClick={() => setStart(addDays(start, 7))}>
          <IconChevronRight size={18} />
        </ActionIcon>
      </Group>
      <Box style={{ overflowX: 'auto' }}>
        <Box style={{ minWidth: 180 + DAYS * W }}>
          <div style={{ display: 'flex', borderBottom: '1px solid var(--mantine-color-default-border)' }}>
            <div style={{ width: 180, flex: 'none' }} />
            {days.map((d) => {
              const l = dayLabel(d, i18n.language);
              return (
                <div key={d} style={{ width: W, flex: 'none', textAlign: 'center', padding: '4px 0', background: d === today ? 'var(--mantine-color-lagoon-light)' : weekday(d) >= 5 ? 'var(--mantine-color-default-hover)' : undefined }}>
                  <Text size="xs" c="dimmed">
                    {l.weekday}
                  </Text>
                  <Text size="sm" fw={600}>
                    {l.day}
                  </Text>
                </div>
              );
            })}
          </div>
          {vehicles.map((v) => (
            <div key={v.id} style={{ display: 'flex', borderBottom: '1px solid var(--mantine-color-default-border)' }} data-schedule-vehicle={v.code}>
              <div style={{ width: 180, flex: 'none', padding: '6px 10px' }}>
                <Text size="sm" fw={600}>
                  {v.code}
                </Text>
                <Text size="xs" c="dimmed" truncate>
                  {t(`vehicles.kinds.${v.kind}`)}
                  {v.status === 'maintenance' ? ` · ${t('vehicles.vehicle_status.maintenance')}` : ''}
                </Text>
              </div>
              {days.map((d, i) => {
                const [a, b] = bounds[i];
                const r = active.find((x) => x.vehicle_id === v.id && x.start_at < b && (x.returned_at ?? x.end_at) > a);
                return (
                  <div key={d} style={{ width: W, flex: 'none', padding: 3, borderLeft: '1px solid var(--mantine-color-default-border)' }}>
                    {r ? (
                      <Tooltip label={`${r.number} · ${r.guest_name}`}>
                        <Box
                          onClick={() => actions.open(r.id)}
                          style={{ cursor: 'pointer', borderRadius: 4, height: 30, background: `var(--mantine-color-${COLORS[r.status] ?? 'gray'}-light)`, borderLeft: `3px solid var(--mantine-color-${COLORS[r.status] ?? 'gray'}-6)`, overflow: 'hidden', padding: '2px 4px' }}
                        >
                          <Text size="10px" fw={600} truncate>
                            {r.guest_name}
                          </Text>
                        </Box>
                      </Tooltip>
                    ) : (
                      <Box
                        onClick={() => can('vehicles.rent') && v.status === 'available' && actions.create({ vehicle_id: v.id, day: d })}
                        style={{ height: 30, cursor: can('vehicles.rent') && v.status === 'available' ? 'pointer' : undefined }}
                        data-free-cell={`${v.code}-${d}`}
                      />
                    )}
                  </div>
                );
              })}
            </div>
          ))}
        </Box>
      </Box>
    </Card>
  );
}
