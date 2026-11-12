import { useState } from 'react';
import { useNavigate } from 'react-router';
import { Alert, Badge, Button, Card, Group, Loader, Modal, NumberInput, Select, SimpleGrid, Stack, Text, UnstyledButton } from '@mantine/core';
import { IconBellRinging, IconPaperBag, IconPlus, IconToolsKitchen } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { api } from '@/api/client';
import { useHotelMutation, useHotelQuery } from '@/api/hooks';
import type { FloorTable, GuestRef, OrderSummary, OrderType, RestaurantOrder } from '@/api/types';
import { useAuth, useHotel } from '@/auth/AuthProvider';
import { EmptyState, SubmitButton } from '@/components/ui';
import { errorMessage } from '@/lib/errors';
import { formatMoney } from '@/lib/format';
import { minutesSince } from './shared';

type Opening = { type: OrderType; table?: FloorTable };

export default function FloorTab({ outletId }: { outletId: string | null }) {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const { can } = useAuth();
  const navigate = useNavigate();
  const floor = useHotelQuery<FloorTable[]>('restaurant_order', '/restaurant/floor', { outlet_id: outletId }, !!outletId);
  const orders = useHotelQuery<OrderSummary[]>('restaurant_order', '/restaurant/orders', { outlet_id: outletId, status: 'open' }, !!outletId);
  const [opening, setOpening] = useState<Opening | null>(null);
  if (!outletId || floor.isPending) return <Loader size="sm" />;
  const canOrder = can('restaurant.order');
  const others = (orders.data ?? []).filter((o) => !o.table_id);
  const now = Date.now();
  const money = (v: string) => formatMoney(v, hotel.currency_code, i18n.language);
  const open = (o: { id: string }) => navigate(`/restaurant/orders/${o.id}`);

  return (
    <Stack>
      {canOrder && (
        <Group gap="xs">
          <Button variant="default" leftSection={<IconPaperBag size={16} />} onClick={() => setOpening({ type: 'takeaway' })}>
            {t('restaurant.order_types.takeaway')}
          </Button>
          <Button variant="default" leftSection={<IconToolsKitchen size={16} />} onClick={() => setOpening({ type: 'room_service' })}>
            {t('restaurant.order_types.room_service')}
          </Button>
        </Group>
      )}
      {floor.data && floor.data.length === 0 ? (
        <EmptyState title={t('restaurant.no_tables')} description={can('restaurant.manage') ? t('restaurant.no_tables_hint') : undefined} />
      ) : (
        <SimpleGrid cols={{ base: 2, sm: 3, md: 4, xl: 6 }} spacing="sm">
          {floor.data?.map((table) => {
            const o = table.order;
            const color = !o ? 'teal' : o.lines_ready > 0 ? 'orange' : 'blue';
            return (
              <UnstyledButton
                key={table.id}
                data-table={table.label}
                onClick={() => (o ? open(o) : canOrder && setOpening({ type: 'dine_in', table }))}
                disabled={!o && !canOrder}
              >
                <Card padding="md" withBorder style={{ borderLeft: `5px solid var(--mantine-color-${color}-6)`, minHeight: 112 }}>
                  <Group justify="space-between" wrap="nowrap" align="flex-start">
                    <div>
                      <Text fw={800} size="xl">
                        {table.label}
                      </Text>
                      <Text size="xs" c="dimmed">
                        {table.area ? `${table.area} · ` : ''}
                        {t('restaurant.seats', { count: table.seats })}
                      </Text>
                    </div>
                    {o && o.lines_ready > 0 && (
                      <Badge color="orange" variant="filled" leftSection={<IconBellRinging size={10} />}>
                        {t('restaurant.ready_count', { count: o.lines_ready })}
                      </Badge>
                    )}
                  </Group>
                  {o ? (
                    <>
                      <Text size="sm" fw={600} mt={6} className="hms-num">
                        {money(o.total)}
                      </Text>
                      <Text size="xs" c="dimmed">
                        {o.number} · {t('restaurant.covers_n', { count: o.covers })} · {t('restaurant.minutes', { count: minutesSince(o.opened_at, now) })}
                      </Text>
                    </>
                  ) : (
                    <Text size="sm" c="teal.7" mt={6} fw={600}>
                      {t('restaurant.free')}
                    </Text>
                  )}
                </Card>
              </UnstyledButton>
            );
          })}
        </SimpleGrid>
      )}
      {others.length > 0 && (
        <>
          <Text fw={600} mt="md">
            {t('restaurant.other_orders')}
          </Text>
          <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }} spacing="sm">
            {others.map((o) => (
              <UnstyledButton key={o.id} onClick={() => open(o)} data-order={o.number}>
                <Card padding="sm" withBorder>
                  <Group justify="space-between">
                    <Text fw={600}>
                      {t(`restaurant.order_types.${o.order_type}`)} · {o.number}
                    </Text>
                    <Text fw={600} className="hms-num">
                      {money(o.total)}
                    </Text>
                  </Group>
                  <Text size="xs" c="dimmed">
                    {o.guest ? `${t('restaurant.room_n', { number: o.guest.room_number })} · ${o.guest.guest_name}` : t('restaurant.covers_n', { count: o.covers })}
                    {o.lines_ready > 0 ? ` · ${t('restaurant.ready_count', { count: o.lines_ready })}` : ''}
                  </Text>
                </Card>
              </UnstyledButton>
            ))}
          </SimpleGrid>
        </>
      )}
      {opening && <OpenOrderModal outletId={outletId} opening={opening} onClose={() => setOpening(null)} onOpened={open} />}
    </Stack>
  );
}

function OpenOrderModal({ outletId, opening, onClose, onOpened }: { outletId: string; opening: Opening; onClose: () => void; onOpened: (o: RestaurantOrder) => void }) {
  const { t } = useTranslation();
  const [covers, setCovers] = useState<number | string>(opening.table ? Math.min(2, opening.table.seats) : 1);
  const [guest, setGuest] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [error, setError] = useState<string | null>(null);
  const needGuest = opening.type === 'room_service';
  const guests = useHotelQuery<GuestRef[]>('reservation', '/in-house-guests', { q: search || undefined }, needGuest);
  const create = useHotelMutation<Record<string, unknown>, RestaurantOrder>((h, body) => api.post<RestaurantOrder>(h('/restaurant/orders'), body), ['restaurant_order']);
  const valid = Number(covers) >= 1 && (!needGuest || !!guest);
  return (
    <Modal
      opened
      onClose={onClose}
      title={opening.table ? t('restaurant.open_table', { table: opening.table.label }) : t(`restaurant.order_types.${opening.type}`)}
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!valid) return;
          create
            .mutateAsync({ outlet_id: outletId, order_type: opening.type, table_id: opening.table?.id, covers: Number(covers), reservation_room_id: guest ?? undefined })
            .then(onOpened, (err) => setError(errorMessage(err)));
        }}
      >
        <Stack>
          {error && <Alert color="red">{error}</Alert>}
          <NumberInput label={t('restaurant.covers')} min={1} max={200} value={covers} onChange={setCovers} data-autofocus />
          {needGuest && (
            <Select
              label={t('restaurant.guest_room')}
              searchable
              required
              searchValue={search}
              onSearchChange={setSearch}
              data={(guests.data ?? []).map((g) => ({ value: g.reservation_room_id, label: `${g.room_number ?? '—'} · ${g.guest_name}` }))}
              value={guest}
              onChange={setGuest}
              nothingFoundMessage={t('restaurant.no_guest_found')}
            />
          )}
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <SubmitButton loading={create.isPending} disabled={!valid} leftSection={<IconPlus size={16} />}>
              {t('restaurant.open_order')}
            </SubmitButton>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}
