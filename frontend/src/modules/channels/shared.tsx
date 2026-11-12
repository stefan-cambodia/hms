import { Badge } from '@mantine/core';
import { useTranslation } from 'react-i18next';

import type { ChannelBooking, ChannelState } from '@/api/types';

export const STATE_COLORS: Record<ChannelState, string> = {
  credentials_saved: 'gray',
  test_ok: 'blue',
  live: 'teal',
  degraded: 'orange',
  paused: 'gray',
};

export function StateBadge({ state }: { state: ChannelState }) {
  const { t } = useTranslation();
  return (
    <Badge color={STATE_COLORS[state]} variant={state === 'live' ? 'filled' : 'light'} data-state={state}>
      {t(`channels.states.${state}`)}
    </Badge>
  );
}

const IMPORT_COLORS: Record<ChannelBooking['import_status'], string> = {
  pending: 'yellow',
  imported: 'teal',
  failed: 'red',
  ignored: 'gray',
};

export function ImportBadge({ status }: { status: ChannelBooking['import_status'] }) {
  const { t } = useTranslation();
  return (
    <Badge color={IMPORT_COLORS[status]} variant="light">
      {t(`channels.import_statuses.${status}`)}
    </Badge>
  );
}
