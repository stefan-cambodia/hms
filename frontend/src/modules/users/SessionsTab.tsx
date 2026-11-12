import { Badge, Button, Group, Stack, Table, Text } from '@mantine/core';
import { modals } from '@mantine/modals';
import { useTranslation } from 'react-i18next';

import { api } from '@/api/client';
import { useHotelMutation, useHotelQuery } from '@/api/hooks';
import type { ConnectedSession } from '@/api/types';
import { useHotel } from '@/auth/AuthProvider';
import { EmptyState } from '@/components/ui';
import { notifyError, notifySuccess } from '@/lib/errors';
import { formatDateTime, formatRelative } from '@/lib/format';

export function describeAgent(ua: string | null): string {
  if (!ua) return '—';
  const browser = /Edg\//.test(ua) ? 'Edge' : /Firefox\//.test(ua) ? 'Firefox' : /Chrome\//.test(ua) ? 'Chrome' : /Safari\//.test(ua) ? 'Safari' : /tauri/i.test(ua) ? 'Desktop app' : '';
  const os = /iPad/.test(ua) ? 'iPadOS' : /Android/.test(ua) ? 'Android' : /Windows/.test(ua) ? 'Windows' : /Mac OS/.test(ua) ? 'macOS' : /Linux/.test(ua) ? 'Linux' : '';
  return [browser, os].filter(Boolean).join(' · ') || ua.slice(0, 60);
}

export default function SessionsTab() {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const sessions = useHotelQuery<ConnectedSession[]>('session', '/sessions');
  const revoke = useHotelMutation<string, void>((h, id) => api.delete(h(`/sessions/${id}`)), ['session', 'user']);
  const online = sessions.data?.filter((s) => s.online).length ?? 0;

  const confirmRevoke = (s: ConnectedSession) =>
    modals.openConfirmModal({
      title: t('sessions.revoke_title', { name: s.user_full_name }),
      children: <Text size="sm">{t('sessions.revoke_body')}</Text>,
      labels: { confirm: t('sessions.revoke'), cancel: t('common.cancel') },
      confirmProps: { color: 'red' },
      onConfirm: () => void revoke.mutateAsync(s.id).then(() => notifySuccess(t('sessions.revoked')), notifyError),
    });

  if (sessions.data?.length === 0) return <EmptyState title={t('sessions.empty')} />;
  return (
    <Stack>
      <Text size="sm" c="dimmed">
        {t('sessions.summary', { online, total: sessions.data?.length ?? 0 })}
      </Text>
      <div className="hms-table-wrap">
        <Table miw={760}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t('users.user')}</Table.Th>
              <Table.Th>{t('sessions.device')}</Table.Th>
              <Table.Th>{t('sessions.last_activity')}</Table.Th>
              <Table.Th>{t('sessions.signed_in')}</Table.Th>
              <Table.Th>{t('sessions.ip')}</Table.Th>
              <Table.Th w={110} />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {sessions.data?.map((s) => (
              <Table.Tr key={s.id}>
                <Table.Td>
                  <Group gap={6}>
                    <Badge variant="dot" color={s.online ? 'lagoon' : 'gray'} size="sm">
                      {s.online ? t('sessions.online') : t('sessions.idle')}
                    </Badge>
                    <div>
                      <Text size="sm" fw={600}>
                        {s.user_full_name}
                      </Text>
                      <Text size="xs" c="dimmed">
                        {s.user_email}
                      </Text>
                    </div>
                  </Group>
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{s.device_label ?? '—'}</Text>
                  <Text size="xs" c="dimmed">
                    {describeAgent(s.user_agent)}
                  </Text>
                </Table.Td>
                <Table.Td>{formatRelative(s.last_seen_at, i18n.language)}</Table.Td>
                <Table.Td>{formatDateTime(s.created_at, i18n.language, hotel.timezone)}</Table.Td>
                <Table.Td>
                  <Text size="sm" ff="monospace">
                    {s.ip ?? '—'}
                  </Text>
                </Table.Td>
                <Table.Td>
                  {s.current ? (
                    <Badge variant="light">{t('sessions.this_device')}</Badge>
                  ) : (
                    <Button size="xs" variant="light" color="red" onClick={() => confirmRevoke(s)}>
                      {t('sessions.revoke')}
                    </Button>
                  )}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </div>
    </Stack>
  );
}
