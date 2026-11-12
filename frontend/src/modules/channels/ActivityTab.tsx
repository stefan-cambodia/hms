import { useState } from 'react';
import { Badge, Code, Loader, Modal, ScrollArea, Stack, Switch, Table, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';

import { useHotelQuery } from '@/api/hooks';
import type { ChannelConnection, ChannelMessage, ChannelMessageDetail } from '@/api/types';
import { useAuth, useHotel } from '@/auth/AuthProvider';
import { EmptyState } from '@/components/ui';
import { formatDateTime } from '@/lib/format';

const OUTCOME_COLORS = { ok: 'teal', warning: 'yellow', error: 'red' } as const;

export default function ActivityTab({ conn }: { conn: ChannelConnection }) {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const { can } = useAuth();
  const [errorsOnly, setErrorsOnly] = useState(false);
  const [open, setOpen] = useState<number | null>(null);
  const messages = useHotelQuery<ChannelMessage[]>('channel_message', `/channel-connections/${conn.id}/messages`, { errors_only: errorsOnly || undefined, limit: 200 });
  const detailAllowed = can('channels.manage');
  return (
    <Stack>
      <Switch label={t('channels.errors_only')} checked={errorsOnly} onChange={(e) => setErrorsOnly(e.currentTarget.checked)} />
      {messages.isPending ? (
        <Loader size="sm" />
      ) : (messages.data ?? []).length === 0 ? (
        <EmptyState title={t('channels.no_messages')} />
      ) : (
        <Table.ScrollContainer minWidth={760}>
          <Table verticalSpacing={6} highlightOnHover={detailAllowed} data-testid="channel-messages">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t('channels.time')}</Table.Th>
                <Table.Th>{t('channels.operation')}</Table.Th>
                <Table.Th>{t('channels.result')}</Table.Th>
                <Table.Th>HTTP</Table.Th>
                <Table.Th>{t('channels.duration')}</Table.Th>
                <Table.Th>{t('channels.summary')}</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {messages.data?.map((m) => (
                <Table.Tr key={m.id} style={{ cursor: detailAllowed ? 'pointer' : undefined }} onClick={() => detailAllowed && setOpen(m.id)}>
                  <Table.Td>
                    <Text size="sm">{formatDateTime(m.at, i18n.language, hotel.timezone)}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Code>{m.operation}</Code>
                  </Table.Td>
                  <Table.Td>
                    <Badge color={OUTCOME_COLORS[m.outcome]} variant="light">
                      {t(`channels.outcomes.${m.outcome}`)}
                    </Badge>
                  </Table.Td>
                  <Table.Td className="hms-num">{m.http_status ?? '—'}</Table.Td>
                  <Table.Td className="hms-num">{m.duration_ms != null ? `${m.duration_ms} ms` : '—'}</Table.Td>
                  <Table.Td maw={420}>
                    <Text size="sm" lineClamp={2}>
                      {m.summary}
                    </Text>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
      {open !== null && <MessageModal id={open} onClose={() => setOpen(null)} />}
    </Stack>
  );
}

function MessageModal({ id, onClose }: { id: number; onClose: () => void }) {
  const { t } = useTranslation();
  const detail = useHotelQuery<ChannelMessageDetail>('channel_message', `/channel-messages/${id}`);
  return (
    <Modal opened onClose={onClose} size="xl" title={t('channels.message')}>
      {!detail.data ? (
        <Loader size="sm" />
      ) : (
        <Stack>
          <Text size="sm">{detail.data.summary}</Text>
          <Text size="xs" c="dimmed">
            {t('channels.redacted_hint')}
          </Text>
          {(['request_body', 'response_body'] as const).map((k) => (
            <div key={k}>
              <Text fw={600} size="sm" mb={4}>
                {k === 'request_body' ? t('channels.request') : t('channels.response')}
              </Text>
              <ScrollArea.Autosize mah={260}>
                <Code block style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                  {detail.data[k] ?? '—'}
                </Code>
              </ScrollArea.Autosize>
            </div>
          ))}
        </Stack>
      )}
    </Modal>
  );
}
