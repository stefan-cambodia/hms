import { useEffect, useState } from 'react';
import { Badge, Button, Card, Drawer, Group, Loader, SegmentedControl, SimpleGrid, Stack, Switch, Text, Title } from '@mantine/core';
import { IconClock } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { api } from '@/api/client';
import { useHotelMutation, useHotelQuery } from '@/api/hooks';
import type { KitchenTicket, MenuItem, OrderLine, RestaurantOrder } from '@/api/types';
import { useAuth } from '@/auth/AuthProvider';
import { EmptyState } from '@/components/ui';
import { notifyError } from '@/lib/errors';
import { LineStatusBadge, minutesSince, useLocalized, useMenu } from './shared';

/** Kitchen / bar display: what to prepare, oldest first. */
export default function KitchenTab({ outletId }: { outletId: string | null }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const loc = useLocalized();
  const [station, setStation] = useState<'kitchen' | 'bar' | 'all'>('kitchen');
  const [soldOut, setSoldOut] = useState(false);
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(timer);
  }, []);
  const tickets = useHotelQuery<KitchenTicket[]>('restaurant_order', '/restaurant/kitchen', {
    outlet_id: outletId,
    station: station === 'all' ? undefined : station,
  });
  const setStatus = useHotelMutation<{ order: string; line: string; status: string }, RestaurantOrder>(
    (h, { order, line, status }) => api.post<RestaurantOrder>(h(`/restaurant/orders/${order}/lines/${line}/status`), { status }),
    ['restaurant_order'],
  );
  const kitchen = can('restaurant.kitchen');
  const advance = (ticket: KitchenTicket, line: OrderLine) => {
    const next = line.status === 'sent' ? 'preparing' : line.status === 'preparing' ? 'ready' : 'served';
    return setStatus.mutateAsync({ order: ticket.order_id, line: line.id, status: next }).catch(notifyError);
  };
  const allReady = async (ticket: KitchenTicket) => {
    for (const line of ticket.lines.filter((l) => l.status === 'sent' || l.status === 'preparing')) {
      await setStatus.mutateAsync({ order: ticket.order_id, line: line.id, status: 'ready' }).catch(notifyError);
    }
  };

  return (
    <Stack>
      <Group justify="space-between">
        <SegmentedControl
          value={station}
          onChange={(v) => setStation(v as typeof station)}
          data={(['kitchen', 'bar', 'all'] as const).map((s) => ({ value: s, label: t(`restaurant.stations.${s}`) }))}
        />
        {(kitchen || can('restaurant.manage')) && (
          <Button variant="default" onClick={() => setSoldOut(true)}>
            {t('restaurant.sold_out_items')}
          </Button>
        )}
      </Group>
      {tickets.isPending ? (
        <Loader size="sm" />
      ) : (tickets.data ?? []).length === 0 ? (
        <EmptyState title={t('restaurant.kitchen_empty')} />
      ) : (
        <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} spacing="sm">
          {tickets.data?.map((ticket) => {
            const oldest = ticket.lines.reduce<string | null>((m, l) => (!m || (l.sent_at && l.sent_at < m) ? l.sent_at : m), null);
            const age = minutesSince(oldest, now);
            return (
              <Card key={ticket.order_id} withBorder padding="sm" data-ticket={ticket.number} style={{ borderTop: `4px solid var(--mantine-color-${age >= 20 ? 'red' : age >= 10 ? 'orange' : 'teal'}-6)` }}>
                <Group justify="space-between" mb={6}>
                  <Title order={4}>{ticket.table_label ? t('restaurant.table_n', { table: ticket.table_label }) : t(`restaurant.order_types.${ticket.order_type}`)}</Title>
                  <Badge variant="light" color={age >= 20 ? 'red' : 'gray'} leftSection={<IconClock size={10} />}>
                    {t('restaurant.minutes', { count: age })}
                  </Badge>
                </Group>
                <Text size="xs" c="dimmed" mb={6}>
                  {ticket.number} · {t('restaurant.covers_n', { count: ticket.covers })}
                  {ticket.room_number ? ` · ${t('restaurant.room_n', { number: ticket.room_number })}` : ''}
                </Text>
                <Stack gap={6}>
                  {ticket.lines.map((line) => (
                    <Group key={line.id} justify="space-between" wrap="nowrap" align="flex-start">
                      <div>
                        <Text fw={700}>
                          {line.quantity} × {loc(line.name)}
                        </Text>
                        {line.notes && (
                          <Text size="sm" c="orange.8" fw={600}>
                            {line.notes}
                          </Text>
                        )}
                      </div>
                      {kitchen && line.status !== 'ready' ? (
                        <Button size="xs" variant={line.status === 'sent' ? 'default' : 'filled'} color={line.status === 'preparing' ? 'teal' : undefined} onClick={() => void advance(ticket, line)}>
                          {line.status === 'sent' ? t('restaurant.start_preparing') : t('restaurant.mark_ready')}
                        </Button>
                      ) : (
                        <LineStatusBadge status={line.status} />
                      )}
                    </Group>
                  ))}
                </Stack>
                {kitchen && ticket.lines.some((l) => l.status === 'sent' || l.status === 'preparing') && (
                  <Button mt="sm" fullWidth color="teal" variant="light" onClick={() => void allReady(ticket)}>
                    {t('restaurant.all_ready')}
                  </Button>
                )}
              </Card>
            );
          })}
        </SimpleGrid>
      )}
      <Drawer opened={soldOut} onClose={() => setSoldOut(false)} position="right" title={<Title order={4}>{t('restaurant.sold_out_items')}</Title>}>
        {soldOut && <SoldOutList outletId={outletId} />}
      </Drawer>
    </Stack>
  );
}

function SoldOutList({ outletId }: { outletId: string | null }) {
  const { t } = useTranslation();
  const loc = useLocalized();
  const menu = useMenu(outletId);
  const toggle = useHotelMutation<{ item: MenuItem; available: boolean }, MenuItem>(
    (h, { item, available }) => api.post<MenuItem>(h(`/restaurant/menu-items/${item.id}/availability`), { is_available: available }),
    ['menu_item'],
  );
  return (
    <Stack gap="xs">
      <Text size="sm" c="dimmed">
        {t('restaurant.sold_out_hint')}
      </Text>
      {menu.items.map((item) => (
        <Switch
          key={item.id}
          label={loc(item.name)}
          checked={item.is_available}
          onChange={(e) => void toggle.mutateAsync({ item, available: e.currentTarget.checked }).catch(notifyError)}
        />
      ))}
    </Stack>
  );
}
