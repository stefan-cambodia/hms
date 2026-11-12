import { Badge, type BadgeProps } from '@mantine/core';
import { useTranslation } from 'react-i18next';

import type { RentalStatus, VehicleKind } from '@/api/types';

export const KINDS: VehicleKind[] = ['scooter', 'motorbike', 'car', 'van', 'bicycle', 'e_bike', 'tuk_tuk', 'boat', 'other'];
const STATUS_COLORS: Record<RentalStatus, string> = { reserved: 'blue', out: 'orange', returned: 'teal', cancelled: 'gray', no_show: 'gray' };

export function RentalStatusBadge({ status, overdue, ...props }: { status: RentalStatus; overdue?: boolean } & BadgeProps) {
  const { t } = useTranslation();
  if (overdue)
    return (
      <Badge color="red" variant="filled" radius="sm" {...props}>
        {t('vehicles.overdue')}
      </Badge>
    );
  return (
    <Badge color={STATUS_COLORS[status]} variant="light" radius="sm" {...props}>
      {t(`vehicles.statuses.${status}`)}
    </Badge>
  );
}

/** Fuel gauge in eighths of a tank ("6/8"). */
export function fuelLabel(eighths: number | null | undefined): string {
  return eighths === null || eighths === undefined ? '—' : `${eighths}/8`;
}
