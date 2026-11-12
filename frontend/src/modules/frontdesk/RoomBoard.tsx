import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router';
import { Badge, Card, Group, Loader, Menu, SegmentedControl, SimpleGrid, Stack, Text, UnstyledButton } from '@mantine/core';
import { IconTool } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { api } from '@/api/client';
import { useHotelMutation, useHotelQuery } from '@/api/hooks';
import type { HousekeepingStatus, RoomBoardRow } from '@/api/types';
import { useAuth } from '@/auth/AuthProvider';
import { EmptyState } from '@/components/ui';
import { notifyError } from '@/lib/errors';
import { formatDate } from '@/lib/format';
import { useInventory } from '@/modules/reservations/shared';

export const HK_STATUSES: HousekeepingStatus[] = ['clean', 'inspected', 'in_progress', 'dirty'];
const HK_COLORS: Record<HousekeepingStatus, string> = { clean: 'teal', inspected: 'blue', in_progress: 'yellow', dirty: 'red' };

export function HousekeepingBadge({ status }: { status: HousekeepingStatus }) {
  const { t } = useTranslation();
  return (
    <Badge size="xs" color={HK_COLORS[status]} variant="light" radius="sm" style={{ overflow: 'visible', flexShrink: 0 }}>
      {t(`rooms.hk.${status}`)}
    </Badge>
  );
}

type Filter = 'all' | 'vacant' | 'occupied' | 'dirty';

function state(room: RoomBoardRow): 'blocked' | 'occupied' | 'arriving' | 'vacant' {
  if (room.block && !room.occupant) return 'blocked';
  if (room.occupant) return 'occupied';
  if (room.arriving) return 'arriving';
  return 'vacant';
}

const STATE_COLORS = { blocked: 'gray', occupied: 'blue', arriving: 'brass', vacant: 'teal' } as const;

/** Every room's situation right now: occupancy, arrivals, cleaning status. */
export function RoomBoard() {
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const navigate = useNavigate();
  const inv = useInventory();
  const board = useHotelQuery<RoomBoardRow[]>('room_board', '/room-board');
  const [filter, setFilter] = useState<Filter>('all');
  const setStatus = useHotelMutation<{ id: string; status: HousekeepingStatus }, unknown>(
    (h, { id, status }) => api.post(h(`/rooms/${id}/housekeeping-status`), { status }),
    ['room_board', 'front_desk', 'room'],
  );
  const rooms = useMemo(() => {
    const all = board.data ?? [];
    switch (filter) {
      case 'vacant':
        return all.filter((r) => state(r) === 'vacant' || state(r) === 'arriving');
      case 'occupied':
        return all.filter((r) => state(r) === 'occupied');
      case 'dirty':
        return all.filter((r) => r.housekeeping_status === 'dirty' || r.housekeeping_status === 'in_progress');
      default:
        return all;
    }
  }, [board.data, filter]);
  if (board.isPending) return <Loader size="sm" />;
  const canClean = can('housekeeping.update');

  return (
    <Stack>
      <Group justify="space-between" wrap="wrap">
        <SegmentedControl
          value={filter}
          onChange={(v) => setFilter(v as Filter)}
          data={(['all', 'vacant', 'occupied', 'dirty'] as Filter[]).map((f) => ({ value: f, label: t(`frontdesk.board_filters.${f}`) }))}
        />
        <Group gap="xs">
          {(['vacant', 'arriving', 'occupied', 'blocked'] as const).map((s) => (
            <Badge key={s} color={STATE_COLORS[s]} variant="dot">
              {t(`frontdesk.room_states.${s}`)}
            </Badge>
          ))}
        </Group>
      </Group>
      {rooms.length === 0 ? (
        <EmptyState title={t('frontdesk.no_rooms')} />
      ) : (
        <SimpleGrid cols={{ base: 2, sm: 3, md: 4, xl: 6 }} spacing="sm">
          {rooms.map((room) => {
            const s = state(room);
            const stay = room.occupant ?? room.arriving;
            return (
              <Card
                key={room.room_id}
                padding="sm"
                data-room-tile={room.number}
                style={{ borderLeft: `4px solid var(--mantine-color-${STATE_COLORS[s]}-6)` }}
              >
                <Group justify="space-between" wrap="nowrap" align="flex-start">
                  <UnstyledButton onClick={() => stay && navigate(`/reservations/${stay.reservation_id}`)} disabled={!stay} style={{ minWidth: 0, flex: 1 }}>
                    <Text fw={700} size="lg" className="hms-num">
                      {room.number}
                    </Text>
                    <Text size="xs" c="dimmed" truncate>
                      {inv.typeName(room.room_type_id)}
                    </Text>
                  </UnstyledButton>
                  <Menu withinPortal position="bottom-end" disabled={!canClean}>
                    <Menu.Target>
                      <UnstyledButton aria-label={t('frontdesk.change_housekeeping', { room: room.number })} disabled={!canClean} style={{ flexShrink: 0 }}>
                        <HousekeepingBadge status={room.housekeeping_status} />
                      </UnstyledButton>
                    </Menu.Target>
                    <Menu.Dropdown>
                      <Menu.Label>{t('frontdesk.housekeeping_status')}</Menu.Label>
                      {HK_STATUSES.map((hs) => (
                        <Menu.Item
                          key={hs}
                          disabled={hs === room.housekeeping_status}
                          onClick={() => setStatus.mutateAsync({ id: room.room_id, status: hs }).catch(notifyError)}
                        >
                          {t(`rooms.hk.${hs}`)}
                        </Menu.Item>
                      ))}
                    </Menu.Dropdown>
                  </Menu>
                </Group>
                <Text size="xs" mt={6} fw={600} c={STATE_COLORS[s]}>
                  {t(`frontdesk.room_states.${s}`)}
                  {room.departing ? ` · ${t('frontdesk.due_out')}` : ''}
                </Text>
                {stay && (
                  <Text size="xs" truncate>
                    {stay.guest_name} · {formatDate(stay.departure, i18n.language)}
                  </Text>
                )}
                {room.block && <Text size="xs" c="dimmed">{t(`calendar.block_reasons.${room.block.reason}`)}</Text>}
                {(() => {
                  const task = room.tasks.find((x) => x.status === 'pending' || x.status === 'in_progress') ?? room.tasks[0];
                  return task ? (
                    <Text size="xs" c="dimmed" truncate data-board-task={task.status}>
                      {t(`housekeeping.types.${task.task_type}`)} · {t(`housekeeping.statuses.${task.status}`)}
                      {task.assigned_to_name ? ` · ${task.assigned_to_name}` : ''}
                    </Text>
                  ) : null;
                })()}
                {room.maintenance && (
                  <Badge
                    size="xs"
                    mt={4}
                    color={room.maintenance.priority === 'urgent' ? 'red' : room.maintenance.priority === 'high' ? 'orange' : 'gray'}
                    variant="light"
                    leftSection={<IconTool size={10} />}
                    data-board-maintenance
                  >
                    {t('frontdesk.maintenance_open', { count: room.maintenance.open })}
                  </Badge>
                )}
              </Card>
            );
          })}
        </SimpleGrid>
      )}
    </Stack>
  );
}
