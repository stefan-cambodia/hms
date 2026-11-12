import { useMemo, useState } from 'react';
import { Alert, Autocomplete, Button, Group, Loader, Stack, Table, Text } from '@mantine/core';
import { IconDownload } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { api } from '@/api/client';
import { useHotelMutation, useHotelQuery } from '@/api/hooks';
import type { ChannelConnection, ChannelMappings, ChannelProduct, RatePlan, RoomType } from '@/api/types';
import { useAuth, useHotel } from '@/auth/AuthProvider';
import { EmptyState } from '@/components/ui';
import { errorMessage, notifyError, notifySuccess } from '@/lib/errors';
import { formatDateTime } from '@/lib/format';
import { pickLocalized } from '@/lib/localized';

export default function MappingTab({ conn }: { conn: ChannelConnection }) {
  const path = `/channel-connections/${conn.id}/mappings`;
  const mappings = useHotelQuery<ChannelMappings>('channel_mapping', path);
  const types = useHotelQuery<RoomType[]>('room_type', '/room-types');
  const plans = useHotelQuery<RatePlan[]>('rate_plan', '/rate-plans');
  if (!mappings.data || !types.data || !plans.data) return <Loader size="sm" />;
  // Re-mount the editor when the saved mapping changes (after a save or a fetch elsewhere).
  return <MappingEditor key={JSON.stringify([mappings.data.rooms, mappings.data.rates])} conn={conn} mappings={mappings.data} types={types.data} plans={plans.data} />;
}

function MappingEditor({ conn, mappings, types, plans }: { conn: ChannelConnection; mappings: ChannelMappings; types: RoomType[]; plans: RatePlan[] }) {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const { can } = useAuth();
  const manage = can('channels.manage');
  const [rooms, setRooms] = useState<Record<string, string>>(() => Object.fromEntries(mappings.rooms.map((r) => [r.room_type_id, r.external_code])));
  const [rates, setRates] = useState<Record<string, string>>(() =>
    Object.fromEntries(mappings.rates.map((r) => [`${r.room_type_id}:${r.rate_plan_id}`, r.external_code])),
  );
  const [error, setError] = useState<string | null>(null);
  const fetchCodes = useHotelMutation<void, ChannelProduct[]>((h) => api.post(h(`/channel-connections/${conn.id}/products`)), ['channel_mapping', 'channel_message', 'channel_connection']);
  const save = useHotelMutation<Record<string, unknown>, ChannelMappings>((h, body) => api.put(h(`/channel-connections/${conn.id}/mappings`), body), [
    'channel_mapping',
    'channel_connection',
  ]);
  const activeTypes = types.filter((rt) => rt.is_active).sort((a, b) => a.sort_order - b.sort_order || a.code.localeCompare(b.code));
  const activePlans = plans.filter((p) => p.is_active).sort((a, b) => Number(b.is_default) - Number(a.is_default) || a.sort_order - b.sort_order);
  const roomOptions = useMemo(
    () => [...new Map(mappings.products.map((p) => [p.room_code, p.room_name ? `${p.room_code}` : p.room_code])).keys()],
    [mappings.products],
  );
  const rateOptions = (roomCode: string) => [...new Set(mappings.products.filter((p) => p.room_code === roomCode && p.rate_code).map((p) => p.rate_code as string))];
  const productLabel = (roomCode: string, rateCode?: string) => {
    const p = mappings.products.find((x) => x.room_code === roomCode && (rateCode === undefined || x.rate_code === rateCode));
    return rateCode === undefined ? p?.room_name : p?.rate_name;
  };

  const submit = () => {
    setError(null);
    const body = {
      rooms: activeTypes.filter((rt) => rooms[rt.id]?.trim()).map((rt) => ({ room_type_id: rt.id, external_code: rooms[rt.id].trim() })),
      rates: activeTypes.flatMap((rt) =>
        rooms[rt.id]?.trim()
          ? activePlans
              .filter((p) => rates[`${rt.id}:${p.id}`]?.trim())
              .map((p) => ({ room_type_id: rt.id, rate_plan_id: p.id, external_code: rates[`${rt.id}:${p.id}`].trim() }))
          : [],
      ),
    };
    save.mutateAsync(body).then(
      () => notifySuccess(t('channels.mapping_saved')),
      (err) => setError(errorMessage(err)),
    );
  };

  if (activeTypes.length === 0) return <EmptyState title={t('channels.no_room_types')} />;
  return (
    <Stack>
      <Text size="sm" c="dimmed" maw={820}>
        {t('channels.mapping_help')}
      </Text>
      <Group gap="sm">
        {manage && (
          <Button
            variant="default"
            leftSection={<IconDownload size={16} />}
            loading={fetchCodes.isPending}
            onClick={() => fetchCodes.mutateAsync().then((p) => notifySuccess(t('channels.codes_fetched', { count: p.length })), notifyError)}
          >
            {t('channels.fetch_codes')}
          </Button>
        )}
        {mappings.products_fetched_at && (
          <Text size="xs" c="dimmed">
            {t('channels.fetched_at', { time: formatDateTime(mappings.products_fetched_at, i18n.language, hotel.timezone) })}
          </Text>
        )}
      </Group>
      {mappings.unknown_codes.length > 0 && <Alert color="orange">{t('channels.unknown_codes', { codes: mappings.unknown_codes.join(', ') })}</Alert>}
      {error && <Alert color="red">{error}</Alert>}
      <Table.ScrollContainer minWidth={560}>
        <Table verticalSpacing="xs" data-testid="channel-mapping">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t('channels.room_type')}</Table.Th>
              <Table.Th>{t('channels.rate_plan')}</Table.Th>
              <Table.Th w={260}>{t('channels.code')}</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {activeTypes.map((rt) => {
              const roomCode = rooms[rt.id]?.trim() ?? '';
              const typePlans = activePlans.filter((p) => p.room_type_ids.length === 0 || p.room_type_ids.includes(rt.id));
              return [
                <Table.Tr key={rt.id} bg="var(--mantine-color-default-hover)">
                  <Table.Td fw={600}>
                    {pickLocalized(rt.name, i18n.language)} <Text span c="dimmed" size="xs">{rt.code}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm" c="dimmed">
                      {t('channels.availability')}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Autocomplete
                      aria-label={`${t('channels.room_code')} ${rt.code}`}
                      data-room-code={rt.code}
                      placeholder={t('channels.not_sent')}
                      data={roomOptions}
                      maxLength={64}
                      readOnly={!manage}
                      value={rooms[rt.id] ?? ''}
                      onChange={(v) => setRooms((m) => ({ ...m, [rt.id]: v }))}
                      description={roomCode ? productLabel(roomCode) : undefined}
                    />
                  </Table.Td>
                </Table.Tr>,
                ...typePlans.map((p) => (
                  <Table.Tr key={`${rt.id}:${p.id}`}>
                    <Table.Td />
                    <Table.Td>
                      {pickLocalized(p.name, i18n.language)} <Text span c="dimmed" size="xs">{p.code}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Autocomplete
                        aria-label={`${t('channels.rate_code')} ${rt.code} ${p.code}`}
                        data-rate-code={`${rt.code}:${p.code}`}
                        placeholder={t('channels.not_sent')}
                        disabled={!roomCode}
                        data={rateOptions(roomCode)}
                        maxLength={64}
                        readOnly={!manage}
                        value={rates[`${rt.id}:${p.id}`] ?? ''}
                        onChange={(v) => setRates((m) => ({ ...m, [`${rt.id}:${p.id}`]: v }))}
                        description={roomCode && rates[`${rt.id}:${p.id}`] ? productLabel(roomCode, rates[`${rt.id}:${p.id}`]) : undefined}
                      />
                    </Table.Td>
                  </Table.Tr>
                )),
              ];
            })}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      {manage && (
        <Group justify="flex-end">
          <Button loading={save.isPending} onClick={submit}>
            {t('channels.save_mapping')}
          </Button>
        </Group>
      )}
    </Stack>
  );
}
