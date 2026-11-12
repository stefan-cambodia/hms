import { useState } from 'react';
import { Code, Group, Pagination, Select, Stack, Table, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';

import { useHotelQuery } from '@/api/hooks';
import type { AdminUser, AuditEntry, Page } from '@/api/types';
import { useHotel } from '@/auth/AuthProvider';
import { formatDateTime } from '@/lib/format';

const PAGE = 50;
const ENTITIES = ['hotel', 'building', 'floor', 'room_type', 'room', 'amenity', 'facility', 'service', 'tax_rate', 'user', 'role', 'user_session', 'organization'];

function show(value: unknown): string {
  if (value === null || value === undefined) return '∅';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

export default function AuditTab() {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const [page, setPage] = useState(1);
  const [entity, setEntity] = useState<string | null>(null);
  const logs = useHotelQuery<Page<AuditEntry>>('audit', '/audit-logs', { limit: PAGE, offset: (page - 1) * PAGE, entity_type: entity });
  const users = useHotelQuery<AdminUser[]>('user', '/users');
  const userName = (id: string | null) => (id ? (users.data?.find((u) => u.id === id)?.full_name ?? id.slice(0, 8)) : t('audit.system'));
  const total = logs.data?.total ?? 0;

  return (
    <Stack>
      <Group>
        <Select
          placeholder={t('audit.all_entities')}
          clearable
          data={ENTITIES.map((e) => ({ value: e, label: t(`audit.entities.${e}`) }))}
          value={entity}
          onChange={(v) => {
            setEntity(v);
            setPage(1);
          }}
          w={240}
        />
        <Text size="sm" c="dimmed">
          {t('audit.immutable')}
        </Text>
      </Group>
      <div className="hms-table-wrap">
        <Table miw={820} verticalSpacing="xs">
          <Table.Thead>
            <Table.Tr>
              <Table.Th w={170}>{t('audit.when')}</Table.Th>
              <Table.Th w={160}>{t('audit.who')}</Table.Th>
              <Table.Th w={180}>{t('audit.action')}</Table.Th>
              <Table.Th>{t('audit.changes')}</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {logs.data?.items.map((e) => (
              <Table.Tr key={e.id}>
                <Table.Td>
                  <Text size="sm">{formatDateTime(e.at, i18n.language, hotel.timezone)}</Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{userName(e.user_id)}</Text>
                  {e.ip && (
                    <Text size="xs" c="dimmed" ff="monospace">
                      {e.ip}
                    </Text>
                  )}
                </Table.Td>
                <Table.Td>
                  <Text size="sm" fw={500}>
                    {t(`audit.entities.${e.entity_type}`, { defaultValue: e.entity_type })}
                  </Text>
                  <Text size="xs" c="dimmed">
                    {t(`audit.actions.${e.action.split('.').pop()}`, { defaultValue: e.action })}
                  </Text>
                </Table.Td>
                <Table.Td>
                  {e.changes && (
                    <Stack gap={2}>
                      {Object.entries(e.changes)
                        .slice(0, 6)
                        .map(([field, [before, after]]) => (
                          <Text key={field} size="xs" style={{ wordBreak: 'break-word' }}>
                            <Code>{field}</Code> {show(before)} → {show(after)}
                          </Text>
                        ))}
                    </Stack>
                  )}
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
