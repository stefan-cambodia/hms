import { useState } from 'react';
import { Link } from 'react-router';
import { Alert, Anchor, Badge, Button, Group, Loader, Modal, SegmentedControl, Stack, Table, Text, Textarea } from '@mantine/core';
import { IconRotateClockwise } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { api } from '@/api/client';
import { useHotelMutation, useHotelQuery } from '@/api/hooks';
import type { ChannelBooking, ChannelConnection } from '@/api/types';
import { useAuth, useHotel } from '@/auth/AuthProvider';
import { EmptyState, SubmitButton } from '@/components/ui';
import { errorMessage, notifyError, notifySuccess } from '@/lib/errors';
import { formatDate, formatDateTime } from '@/lib/format';
import { ImportBadge } from './shared';

export default function BookingsTab({ conn }: { conn: ChannelConnection }) {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const { can } = useAuth();
  const manage = can('channels.manage');
  const [filter, setFilter] = useState<'attention' | 'all'>(conn.bookings_attention > 0 ? 'attention' : 'all');
  const [dismissing, setDismissing] = useState<ChannelBooking | null>(null);
  const bookings = useHotelQuery<ChannelBooking[]>('channel_booking', '/channel-bookings', { attention: filter === 'attention' || undefined, limit: 200 });
  const retry = useHotelMutation<string, ChannelBooking>((h, id) => api.post(h(`/channel-bookings/${id}/retry`)), ['channel_booking', 'channel_connection', 'reservation']);
  const rows = (bookings.data ?? []).filter((b) => b.connection_id === conn.id);

  const errorText = (b: ChannelBooking) => {
    if (!b.error_code) return b.error_detail;
    const key = `channels.booking_errors.${b.error_code}`;
    return i18n.exists(key) ? `${t(key)}${b.error_detail ? ` — ${b.error_detail}` : ''}` : b.error_detail ?? b.error_code;
  };

  return (
    <Stack>
      <SegmentedControl
        w="fit-content"
        value={filter}
        onChange={(v) => setFilter(v as typeof filter)}
        data={(['attention', 'all'] as const).map((v) => ({ value: v, label: t(`channels.bookings_filter.${v}`) }))}
      />
      {bookings.isPending ? (
        <Loader size="sm" />
      ) : rows.length === 0 ? (
        <EmptyState title={filter === 'attention' ? t('channels.no_attention') : t('channels.no_bookings')} />
      ) : (
        <Table.ScrollContainer minWidth={900}>
          <Table verticalSpacing="xs" striped data-testid="channel-bookings">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t('channels.received')}</Table.Th>
                <Table.Th>{t('channels.channel')}</Table.Th>
                <Table.Th>{t('channels.guest')}</Table.Th>
                <Table.Th>{t('channels.stay')}</Table.Th>
                <Table.Th>{t('channels.result')}</Table.Th>
                <Table.Th>{t('channels.reservation')}</Table.Th>
                {manage && <Table.Th />}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {rows.map((b) => (
                <Table.Tr key={b.id} data-booking={b.external_id}>
                  <Table.Td>
                    <Text size="sm">{formatDateTime(b.received_at, i18n.language, hotel.timezone)}</Text>
                    <Badge size="xs" variant="outline" color={b.action === 'cancel' ? 'red' : b.action === 'modify' ? 'blue' : 'teal'}>
                      {t(`channels.actions.${b.action}`)}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">{b.channel_name ?? '—'}</Text>
                    <Text size="xs" c="dimmed">
                      {b.external_id}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">{b.guest_name ?? '—'}</Text>
                    {b.card_last4 && (
                      <Text size="xs" c="dimmed">
                        {t('channels.card_on_file', { brand: b.card_brand ?? '', last4: b.card_last4 })}
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">{b.arrival ? `${formatDate(b.arrival, i18n.language)} → ${formatDate(b.departure, i18n.language)}` : '—'}</Text>
                    {b.total && (
                      <Text size="xs" c="dimmed" className="hms-num">
                        {b.total} {b.currency}
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td maw={320}>
                    <Group gap={4}>
                      <ImportBadge status={b.import_status} />
                      {b.overbooked && (
                        <Badge color="red" variant="filled">
                          {t('channels.overbooked')}
                        </Badge>
                      )}
                    </Group>
                    {(b.error_code || b.error_detail) && (
                      <Text size="xs" c={b.import_status === 'failed' ? 'red' : 'dimmed'} mt={2}>
                        {errorText(b)}
                      </Text>
                    )}
                    {b.import_status === 'failed' && b.confirmed_at && (
                      <Text size="xs" c="dimmed">
                        {t('channels.error_reported')}
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td>
                    {b.reservation_id ? (
                      <Anchor component={Link} to={`/reservations/${b.reservation_id}`} size="sm">
                        {b.reservation_code}
                      </Anchor>
                    ) : (
                      '—'
                    )}
                  </Table.Td>
                  {manage && (
                    <Table.Td>
                      <Group gap={4} wrap="nowrap">
                        {(b.import_status === 'failed' || b.import_status === 'pending') && (
                          <Button
                            size="xs"
                            variant="light"
                            leftSection={<IconRotateClockwise size={14} />}
                            loading={retry.isPending && retry.variables === b.id}
                            onClick={() =>
                              retry.mutateAsync(b.id).then(
                                (r) => (r.import_status === 'imported' ? notifySuccess(t('channels.retried')) : notifyError(new Error(r.error_code ?? ''))),
                                notifyError,
                              )
                            }
                          >
                            {t('channels.retry')}
                          </Button>
                        )}
                        {(b.import_status === 'failed' || b.import_status === 'pending' || b.overbooked) && (
                          <Button size="xs" variant="subtle" onClick={() => setDismissing(b)}>
                            {t('channels.dismiss')}
                          </Button>
                        )}
                      </Group>
                    </Table.Td>
                  )}
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
      {dismissing && <DismissModal booking={dismissing} onClose={() => setDismissing(null)} />}
    </Stack>
  );
}

function DismissModal({ booking, onClose }: { booking: ChannelBooking; onClose: () => void }) {
  const { t } = useTranslation();
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);
  const dismiss = useHotelMutation<string, ChannelBooking>((h, r) => api.post(h(`/channel-bookings/${booking.id}/dismiss`), { reason: r }), ['channel_booking', 'channel_connection']);
  return (
    <Modal opened onClose={onClose} title={t('channels.dismiss')}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!reason.trim()) return;
          dismiss.mutateAsync(reason.trim()).then(
            () => {
              notifySuccess(t('channels.dismissed'));
              onClose();
            },
            (err) => setError(errorMessage(err)),
          );
        }}
      >
        <Stack>
          {error && <Alert color="red">{error}</Alert>}
          <Textarea label={t('channels.dismiss_reason')} required autosize minRows={2} maxLength={300} value={reason} onChange={(e) => setReason(e.currentTarget.value)} data-autofocus />
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <SubmitButton loading={dismiss.isPending} disabled={!reason.trim()}>
              {t('channels.dismiss')}
            </SubmitButton>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}
