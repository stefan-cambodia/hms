import { useState } from 'react';
import { useSearchParams } from 'react-router';
import { Alert, Badge, Button, Card, Group, Loader, SegmentedControl, SimpleGrid, Stack, Tabs, Text, Title } from '@mantine/core';
import { modals } from '@mantine/modals';
import {
  IconActivity,
  IconAlertTriangle,
  IconInbox,
  IconPlayerPause,
  IconPlayerPlay,
  IconPlugConnected,
  IconPlus,
  IconRefresh,
  IconRoute,
  IconSettings,
  IconTrash,
} from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { api } from '@/api/client';
import { useHotelMutation, useHotelQuery } from '@/api/hooks';
import type { ChannelConnection } from '@/api/types';
import { useAuth, useHotel } from '@/auth/AuthProvider';
import { confirmDelete, PageHeader } from '@/components/ui';
import { errorMessage, notifyError, notifySuccess } from '@/lib/errors';
import { formatDateTime } from '@/lib/format';
import ActivityTab from './ActivityTab';
import BookingsTab from './BookingsTab';
import { ConnectionDrawer } from './ConnectionDrawer';
import MappingTab from './MappingTab';
import { StateBadge } from './shared';

const TABS = ['mapping', 'bookings', 'activity'] as const;
type TabKey = (typeof TABS)[number];
const TAB_ICONS = { mapping: IconRoute, bookings: IconInbox, activity: IconActivity };

export default function ChannelsPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const [search, setSearch] = useSearchParams();
  const [editing, setEditing] = useState<ChannelConnection | 'new' | null>(null);
  const conns = useHotelQuery<ChannelConnection[]>('channel_connection', '/channel-connections');
  const list = conns.data ?? [];
  const selected = list.find((c) => c.id === search.get('connection')) ?? list[0];
  const tab = (TABS as readonly string[]).includes(search.get('tab') ?? '') ? (search.get('tab') as TabKey) : 'mapping';
  const setParam = (key: string, value: string | null) =>
    setSearch(
      (p) => {
        const out = new URLSearchParams(p);
        if (value) out.set(key, value);
        else out.delete(key);
        return out;
      },
      { replace: true },
    );

  return (
    <>
      <PageHeader
        title={t('nav.channels')}
        description={t('channels.description')}
        actions={
          can('channels.manage') && (
            <Button leftSection={<IconPlus size={16} />} onClick={() => setEditing('new')}>
              {t('channels.add')}
            </Button>
          )
        }
      />
      {conns.isPending ? (
        <Loader size="sm" />
      ) : !selected ? (
        <NoConnection />
      ) : (
        <Stack>
          {list.length > 1 && (
            <SegmentedControl value={selected.id} onChange={(id) => setParam('connection', id)} data={list.map((c) => ({ value: c.id, label: c.name }))} />
          )}
          <ConnectionCard conn={selected} onEdit={() => setEditing(selected)} />
          <Tabs value={tab} onChange={(v) => setParam('tab', v)} keepMounted={false}>
            <Tabs.List>
              {TABS.map((k) => {
                const Icon = TAB_ICONS[k];
                return (
                  <Tabs.Tab key={k} value={k} leftSection={<Icon size={16} />}>
                    {t(`channels.tabs.${k}`)}
                    {k === 'bookings' && selected.bookings_attention > 0 && (
                      <Badge ml={6} size="xs" color="red" variant="filled">
                        {selected.bookings_attention}
                      </Badge>
                    )}
                  </Tabs.Tab>
                );
              })}
            </Tabs.List>
            <Tabs.Panel value="mapping" pt="md">
              <MappingTab conn={selected} />
            </Tabs.Panel>
            <Tabs.Panel value="bookings" pt="md">
              <BookingsTab conn={selected} />
            </Tabs.Panel>
            <Tabs.Panel value="activity" pt="md">
              <ActivityTab conn={selected} />
            </Tabs.Panel>
          </Tabs>
        </Stack>
      )}
      <ConnectionDrawer
        value={editing}
        onClose={() => setEditing(null)}
        onSaved={(c) => {
          setEditing(null);
          setParam('connection', c.id);
        }}
      />
    </>
  );
}

function NoConnection() {
  const { t } = useTranslation();
  return (
    <Card withBorder padding="lg" maw={760} data-testid="no-channel">
      <Group gap="sm" mb="sm">
        <IconPlugConnected size={22} />
        <Title order={3}>{t('channels.none_title')}</Title>
      </Group>
      <Stack gap="sm">
        <Text size="sm">{t('channels.none_manual')}</Text>
        <Text size="sm">{t('channels.none_how')}</Text>
        <Text size="sm" c="dimmed">
          {t('channels.none_direct')}
        </Text>
      </Stack>
    </Card>
  );
}

function Stat({ label, value, alert }: { label: string; value: string | number; alert?: boolean }) {
  return (
    <div>
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      <Text fw={600} c={alert ? 'red' : undefined} className="hms-num">
        {value}
      </Text>
    </div>
  );
}

function ConnectionCard({ conn, onEdit }: { conn: ChannelConnection; onEdit: () => void }) {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const { can } = useAuth();
  const manage = can('channels.manage');
  const s = conn.status;
  const when = (iso: string | null) => (iso ? formatDateTime(iso, i18n.language, hotel.timezone) : t('channels.never'));
  const path = `/channel-connections/${conn.id}`;
  const test = useHotelMutation<void, { ok: boolean; message: string }>((h) => api.post(h(`${path}/test`)), ['channel_connection', 'channel_message']);
  const sync = useHotelMutation<void>((h) => api.post(h(`${path}/sync`)), ['channel_connection']);
  const refresh = useHotelMutation<void>((h) => api.post(h(`${path}/full-refresh`)), ['channel_connection']);
  const toggle = useHotelMutation<boolean, ChannelConnection>((h, enabled) => api.patch<ChannelConnection>(h(path), { version: conn.version, enabled }), ['channel_connection']);
  const remove = useHotelMutation<void>((h) => api.delete(h(path)), ['channel_connection']);

  const runTest = () =>
    test.mutateAsync().then(
      (r) =>
        r.ok
          ? notifySuccess(t('channels.test_ok', { message: r.message }))
          : modals.open({ title: t('channels.test'), children: <Alert color="red">{t('channels.test_failed', { message: r.message })}</Alert> }),
      notifyError,
    );
  const fullRefresh = () =>
    modals.openConfirmModal({
      title: t('channels.full_refresh'),
      children: <Text size="sm">{t('channels.full_refresh_confirm', { days: conn.horizon_days })}</Text>,
      labels: { confirm: t('channels.full_refresh'), cancel: t('common.cancel') },
      onConfirm: () => void refresh.mutateAsync().then(() => notifySuccess(t('channels.full_refresh_queued')), notifyError),
    });

  return (
    <Card withBorder padding="md" data-testid="channel-connection" data-connection={conn.name}>
      <Group justify="space-between" align="flex-start" wrap="wrap" gap="sm">
        <div>
          <Group gap="xs">
            <Title order={3}>{conn.name}</Title>
            <StateBadge state={s.state} />
            <Badge variant="outline" color={conn.environment === 'production' ? 'violet' : 'gray'}>
              {t(`channels.environments.${conn.environment}`)}
            </Badge>
          </Group>
          <Text size="sm" c="dimmed">
            {t('channels.providers.siteminder')} · {t('channels.account_code')} {conn.account_code} · {t('channels.hotel_code')} {conn.hotel_code}
          </Text>
        </div>
        {manage && (
          <Group gap="xs">
            <Button variant="default" leftSection={<IconPlugConnected size={16} />} loading={test.isPending} onClick={runTest}>
              {t('channels.test')}
            </Button>
            <Button
              variant="default"
              leftSection={<IconRefresh size={16} />}
              loading={sync.isPending}
              disabled={!conn.enabled}
              onClick={() => sync.mutateAsync().then(() => notifySuccess(t('channels.sync_queued')), notifyError)}
            >
              {t('channels.sync_now')}
            </Button>
            <Button variant="default" disabled={!conn.enabled || !conn.push_ari} loading={refresh.isPending} onClick={fullRefresh}>
              {t('channels.full_refresh')}
            </Button>
            <Button
              variant="default"
              leftSection={conn.enabled ? <IconPlayerPause size={16} /> : <IconPlayerPlay size={16} />}
              loading={toggle.isPending}
              onClick={() => toggle.mutateAsync(!conn.enabled).catch(notifyError)}
            >
              {conn.enabled ? t('channels.pause') : t('channels.resume')}
            </Button>
            <Button variant="default" leftSection={<IconSettings size={16} />} onClick={onEdit}>
              {t('common.edit')}
            </Button>
            <Button
              variant="subtle"
              color="red"
              leftSection={<IconTrash size={16} />}
              onClick={() =>
                confirmDelete({
                  title: t('channels.delete_title'),
                  message: t('channels.delete_message'),
                  onConfirm: () => remove.mutateAsync().then(() => notifySuccess(t('channels.deleted')), notifyError),
                })
              }
            >
              {t('common.delete')}
            </Button>
          </Group>
        )}
      </Group>

      <SimpleGrid cols={{ base: 2, sm: 3, lg: 6 }} mt="md" spacing="sm">
        <Stat label={t('channels.last_push')} value={conn.push_ari ? when(s.last_push_at) : t('channels.disabled')} />
        <Stat label={t('channels.last_pull')} value={conn.pull_reservations ? when(s.last_pull_at) : t('channels.disabled')} />
        <Stat label={t('channels.pending')} value={conn.pending_changes} />
        <Stat label={t('channels.errors_24h')} value={conn.errors_24h} alert={conn.errors_24h > 0} />
        <Stat label={t('channels.attention')} value={conn.bookings_attention} alert={conn.bookings_attention > 0} />
        <Stat label={t('channels.unmapped')} value={conn.unmapped_room_types} alert={conn.unmapped_room_types > 0} />
      </SimpleGrid>

      <Stack gap="xs" mt="md">
        {s.state === 'paused' && <Alert color="gray">{t('channels.paused_hint')}</Alert>}
        {s.state === 'credentials_saved' && <Alert color="blue">{t('channels.not_verified_hint')}</Alert>}
        {s.state === 'degraded' && s.last_error && (
          <Alert color="orange" icon={<IconAlertTriangle size={16} />} title={t('channels.last_error')} data-testid="channel-error">
            <Text size="sm">{s.last_error}</Text>
            {s.next_push_at && (
              <Text size="xs" c="dimmed" mt={4}>
                {t('channels.next_retry', { time: when(s.next_push_at) })}
              </Text>
            )}
          </Alert>
        )}
        {s.last_test_at && (
          <Text size="xs" c={s.last_test_ok ? 'dimmed' : 'red'}>
            {t('channels.last_test')}: {when(s.last_test_at)} · {s.last_test_ok ? t('channels.outcomes.ok') : t('channels.outcomes.error')} · {s.last_test_message}
          </Text>
        )}
        {test.error && <Alert color="red">{errorMessage(test.error)}</Alert>}
      </Stack>
    </Card>
  );
}
