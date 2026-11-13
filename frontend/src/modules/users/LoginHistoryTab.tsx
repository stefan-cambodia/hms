import { useState } from 'react';
import { Badge, Group, Pagination, Stack, Table, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';

import { useHotelQuery } from '@/api/hooks';
import type { LoginEvent, Page } from '@/api/types';
import { useHotel } from '@/auth/AuthProvider';
import { formatDateTime } from '@/lib/format';
import { describeAgent } from './SessionsTab';

const PAGE = 50;

export default function LoginHistoryTab() {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const [page, setPage] = useState(1);
  const events = useHotelQuery<Page<LoginEvent>>('session', '/login-events', { limit: PAGE, offset: (page - 1) * PAGE });
  const total = events.data?.total ?? 0;

  return (
    <Stack>
      <div className="hms-table-wrap">
        <Table miw={720}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t('audit.when')}</Table.Th>
              <Table.Th>{t('auth.email')}</Table.Th>
              <Table.Th>{t('logins.result')}</Table.Th>
              <Table.Th>{t('sessions.device')}</Table.Th>
              <Table.Th>{t('sessions.ip')}</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {events.data?.items.map((e) => (
              <Table.Tr key={e.id}>
                <Table.Td>{formatDateTime(e.at, i18n.language, hotel.timezone)}</Table.Td>
                <Table.Td>{e.email}</Table.Td>
                <Table.Td>
                  {e.success ? (
                    <Badge color={e.reason === 'recovery_code' ? 'orange' : 'lagoon'} variant="light" radius="sm">
                      {e.reason === 'recovery_code' ? t('logins.reasons.recovery_code') : t('logins.success')}
                    </Badge>
                  ) : (
                    <Badge color="red" variant="light" radius="sm">
                      {t(`logins.reasons.${e.reason ?? 'unknown'}`, { defaultValue: t('logins.failed') })}
                    </Badge>
                  )}
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{describeAgent(e.user_agent)}</Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm" ff="monospace">
                    {e.ip ?? '—'}
                  </Text>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </div>
      {total > PAGE && (
        <Group justify="center">
          <Pagination total={Math.ceil(total / PAGE)} value={page} onChange={setPage} />
        </Group>
      )}
    </Stack>
  );
}
