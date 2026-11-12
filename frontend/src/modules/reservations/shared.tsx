import { useMemo } from 'react';
import { Badge, type BadgeProps, Group, Tooltip } from '@mantine/core';
import { IconAlertTriangle, IconPencil } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { useHotelQuery } from '@/api/hooks';
import type { ReservationSource, ReservationStatus, Room, RoomType } from '@/api/types';
import { useHotel } from '@/auth/AuthProvider';
import { hotelToday } from '@/lib/dates';
import { pickLocalized } from '@/lib/localized';
import { STATUS_COLORS } from '@/modules/calendar/layout';

export const STATUSES: ReservationStatus[] = ['pending', 'confirmed', 'checked_in', 'checked_out', 'cancelled', 'no_show'];
export const SOURCES: ReservationSource[] = ['direct', 'phone', 'email', 'walk_in', 'website', 'booking_com', 'agoda', 'other'];

export function StatusBadge({ status, ...props }: { status: ReservationStatus } & BadgeProps) {
  const { t } = useTranslation();
  return (
    <Badge color={STATUS_COLORS[status]} variant={status === 'checked_in' ? 'filled' : 'light'} radius="sm" {...props}>
      {t(`reservations.status.${status}`)}
    </Badge>
  );
}

export function FlagBadges({ modified, overbooked }: { modified?: boolean; overbooked?: boolean }) {
  const { t } = useTranslation();
  return (
    <Group gap={4} wrap="nowrap">
      {modified && (
        <Tooltip label={t('reservations.modified_hint')}>
          <Badge variant="outline" color="gray" radius="sm" leftSection={<IconPencil size={10} />}>
            {t('reservations.modified')}
          </Badge>
        </Tooltip>
      )}
      {overbooked && (
        <Tooltip label={t('reservations.overbooked_hint')}>
          <Badge variant="filled" color="red" radius="sm" leftSection={<IconAlertTriangle size={10} />}>
            {t('reservations.overbooked')}
          </Badge>
        </Tooltip>
      )}
    </Group>
  );
}

/** Rooms and room categories with lookup maps and localized names. */
export function useInventory() {
  const { i18n } = useTranslation();
  const hotel = useHotel();
  const rooms = useHotelQuery<Room[]>('room', '/rooms');
  const types = useHotelQuery<RoomType[]>('room_type', '/room-types');
  return useMemo(() => {
    const roomById = new Map((rooms.data ?? []).map((r) => [r.id, r]));
    const typeById = new Map((types.data ?? []).map((t) => [t.id, t]));
    return {
      loading: rooms.isPending || types.isPending,
      rooms: rooms.data ?? [],
      types: types.data ?? [],
      roomById,
      typeById,
      typeName: (id: string | null | undefined) => (id ? pickLocalized(typeById.get(id)?.name, i18n.language, hotel.default_language) : ''),
      roomNumber: (id: string | null | undefined) => (id ? (roomById.get(id)?.number ?? '?') : null),
    };
  }, [rooms.data, types.data, rooms.isPending, types.isPending, i18n.language, hotel.default_language]);
}

export function useHotelToday(): string {
  const hotel = useHotel();
  return hotelToday(hotel.timezone);
}

export function newIdempotencyKey(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}
