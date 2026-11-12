import { useState } from 'react';
import { Badge, Button, Card, Group, Loader, NumberInput, Table, Text } from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import { IconCheck } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { api } from '@/api/client';
import { useHotelMutation, useHotelQuery } from '@/api/hooks';
import type { BreakfastRow } from '@/api/types';
import { useAuth } from '@/auth/AuthProvider';
import { EmptyState } from '@/components/ui';
import { notifyError } from '@/lib/errors';
import { useHotelToday } from '@/modules/reservations/shared';

/** Breakfasts included in the guests' rates: expected and served. */
export default function BreakfastTab() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const today = useHotelToday();
  const [day, setDay] = useState<string>(today);
  const [covers, setCovers] = useState<Record<string, number | string>>({});
  const list = useHotelQuery<BreakfastRow[]>('restaurant_order', '/restaurant/breakfast', { day });
  const mark = useHotelMutation<{ rr: string; covers: number }, void>((h, { rr, covers: n }) => api.post(h('/restaurant/breakfast'), { reservation_room_id: rr, covers: n, day }), ['restaurant_order']);
  const unmark = useHotelMutation<string, void>((h, rr) => api.delete(h(`/restaurant/breakfast/${rr}?day=${day}`)), ['restaurant_order']);
  const rows = list.data ?? [];
  const expected = rows.reduce((n, r) => n + r.adults + r.children, 0);
  const served = rows.reduce((n, r) => n + (r.served_covers ?? 0), 0);
  const canMark = can('restaurant.order') && day === today;
  return (
    <>
      <Group justify="space-between" mb="md" wrap="wrap">
        <DatePickerInput value={day} onChange={(v) => v && setDay(v)} valueFormat="ddd D MMM YYYY" w={180} aria-label={t('restaurant.day')} />
        <Text fw={600} data-testid="breakfast-count">
          {t('restaurant.breakfast_count', { served, expected })}
        </Text>
      </Group>
      {list.isPending ? (
        <Loader size="sm" />
      ) : rows.length === 0 ? (
        <EmptyState title={t('restaurant.no_breakfast')} description={t('restaurant.no_breakfast_hint')} />
      ) : (
        <Card padding={0}>
          <div className="hms-table-wrap">
            <Table verticalSpacing="sm" miw={560}>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t('rooms.number')}</Table.Th>
                  <Table.Th>{t('reservations.guest')}</Table.Th>
                  <Table.Th>{t('restaurant.included')}</Table.Th>
                  <Table.Th>{t('restaurant.served')}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {rows.map((r) => (
                  <Table.Tr key={r.reservation_room_id} data-breakfast={r.room_number}>
                    <Table.Td fw={700}>{r.room_number ?? '—'}</Table.Td>
                    <Table.Td>
                      <Text size="sm">{r.guest_name}</Text>
                      <Text size="xs" c="dimmed">
                        {r.reservation_code} · {t(`pricing.meal_plans.${r.meal_plan}`)}
                      </Text>
                    </Table.Td>
                    <Table.Td>{t('reservations.guests_count', { adults: r.adults, children: r.children })}</Table.Td>
                    <Table.Td>
                      {r.served_covers ? (
                        <Group gap="xs">
                          <Badge color="teal" variant="light" leftSection={<IconCheck size={10} />}>
                            {t('restaurant.covers_n', { count: r.served_covers })}
                          </Badge>
                          {canMark && (
                            <Button size="xs" variant="subtle" color="gray" onClick={() => void unmark.mutateAsync(r.reservation_room_id).catch(notifyError)}>
                              {t('restaurant.undo')}
                            </Button>
                          )}
                        </Group>
                      ) : canMark ? (
                        <Group gap="xs" wrap="nowrap">
                          <NumberInput
                            size="xs"
                            w={70}
                            min={1}
                            max={r.adults + r.children}
                            value={covers[r.reservation_room_id] ?? r.adults + r.children}
                            onChange={(v) => setCovers({ ...covers, [r.reservation_room_id]: v })}
                            aria-label={t('restaurant.covers')}
                          />
                          <Button
                            size="xs"
                            onClick={() =>
                              void mark.mutateAsync({ rr: r.reservation_room_id, covers: Number(covers[r.reservation_room_id] ?? r.adults + r.children) }).catch(notifyError)
                            }
                          >
                            {t('restaurant.mark_breakfast')}
                          </Button>
                        </Group>
                      ) : (
                        '—'
                      )}
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </div>
        </Card>
      )}
    </>
  );
}
