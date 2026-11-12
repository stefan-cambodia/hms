import { Alert, Badge, Tooltip } from '@mantine/core';
import { IconPlugConnectedX } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { useConnectionStatus } from '@/api/realtime';

export function ConnectionIndicator() {
  const { t } = useTranslation();
  const status = useConnectionStatus();
  const color = status === 'online' ? 'lagoon' : status === 'connecting' ? 'yellow' : 'red';
  return (
    <Tooltip label={t(`connection.${status}_hint`)}>
      <Badge variant="dot" color={color} size="lg" radius="sm" style={{ textTransform: 'none' }}>
        {t(`connection.${status}`)}
      </Badge>
    </Tooltip>
  );
}

export function ConnectionBanner() {
  const { t } = useTranslation();
  const status = useConnectionStatus();
  if (status !== 'offline') return null;
  return (
    <Alert color="red" variant="light" radius={0} icon={<IconPlugConnectedX size={18} />} title={t('connection.banner_title')} py="xs">
      {t('connection.banner_body')}
    </Alert>
  );
}
