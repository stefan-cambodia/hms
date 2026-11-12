import { useState } from 'react';
import { Alert, Button, Drawer, Group, NumberInput, PasswordInput, SegmentedControl, Select, SimpleGrid, Stack, Switch, Text, TextInput, Title } from '@mantine/core';
import { useTranslation } from 'react-i18next';

import { api } from '@/api/client';
import { useHotelMutation } from '@/api/hooks';
import type { ChannelConnection } from '@/api/types';
import { SubmitButton } from '@/components/ui';
import { applyFieldErrors, errorMessage, notifySuccess } from '@/lib/errors';

interface Draft {
  name: string;
  environment: 'test' | 'production';
  endpoint_url: string;
  account_code: string;
  username: string;
  password: string;
  hotel_code: string;
  push_ari: boolean;
  pull_reservations: boolean;
  horizon_days: number | string;
  pull_interval_seconds: number | string;
  rate_amount: 'after_tax' | 'before_tax';
}

function draftOf(c: ChannelConnection | null): Draft {
  return {
    name: c?.name ?? 'SiteMinder',
    environment: c?.environment ?? 'test',
    endpoint_url: c?.endpoint_url ?? '',
    account_code: c?.account_code ?? '',
    username: c?.username ?? '',
    password: '',
    hotel_code: c?.hotel_code ?? '',
    push_ari: c?.push_ari ?? true,
    pull_reservations: c?.pull_reservations ?? false,
    horizon_days: c?.horizon_days ?? 365,
    pull_interval_seconds: c?.pull_interval_seconds ?? 180,
    rate_amount: c?.settings.rate_amount ?? 'after_tax',
  };
}

export function ConnectionDrawer({
  value,
  onClose,
  onSaved,
}: {
  value: ChannelConnection | 'new' | null;
  onClose: () => void;
  onSaved: (c: ChannelConnection) => void;
}) {
  const { t } = useTranslation();
  const editing = value && value !== 'new' ? value : null;
  return (
    <Drawer opened={!!value} onClose={onClose} position="right" size="lg" title={<Title order={3}>{editing ? t('channels.edit') : t('channels.add')}</Title>}>
      {value && <ConnectionForm key={editing?.id ?? 'new'} connection={editing} onDone={onSaved} onCancel={onClose} />}
    </Drawer>
  );
}

function ConnectionForm({ connection, onDone, onCancel }: { connection: ChannelConnection | null; onDone: (c: ChannelConnection) => void; onCancel: () => void }) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState<Draft>(() => draftOf(connection));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const save = useHotelMutation<Record<string, unknown>, ChannelConnection>(
    (h, body) => (connection ? api.patch(h(`/channel-connections/${connection.id}`), body) : api.post(h('/channel-connections'), body)),
    ['channel_connection', 'channel_mapping'],
  );
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setDraft((d) => ({ ...d, [k]: v }));
  const field = (k: string) => errors[k] ?? errors[`settings.${k}`];

  const submit = () => {
    setError(null);
    setErrors({});
    const body: Record<string, unknown> = {
      name: draft.name.trim(),
      environment: draft.environment,
      endpoint_url: draft.endpoint_url.trim() || null,
      account_code: draft.account_code.trim(),
      username: draft.username.trim(),
      hotel_code: draft.hotel_code.trim(),
      push_ari: draft.push_ari,
      pull_reservations: draft.pull_reservations,
      horizon_days: Number(draft.horizon_days),
      pull_interval_seconds: Number(draft.pull_interval_seconds),
      settings: { rate_amount: draft.rate_amount },
    };
    if (draft.password) body.password = draft.password;
    if (connection) body.version = connection.version;
    else body.provider = 'siteminder';
    save.mutateAsync(body).then(
      (c) => {
        notifySuccess(t('channels.saved'));
        onDone(c);
      },
      (err) => {
        const found: Record<string, string> = {};
        if (!applyFieldErrors(err, (path, message) => (found[path] = message))) setError(errorMessage(err));
        setErrors(found);
      },
    );
  };

  const required = !!(draft.name.trim() && draft.account_code.trim() && draft.username.trim() && draft.hotel_code.trim() && (connection || draft.password));
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (required) submit();
      }}
    >
      <Stack>
        {error && <Alert color="red">{error}</Alert>}
        <TextInput label={t('channels.provider')} value={t('channels.providers.siteminder')} readOnly />
        <TextInput label={t('channels.name')} required maxLength={100} value={draft.name} onChange={(e) => set('name', e.currentTarget.value)} error={field('name')} />
        <div>
          <Text size="sm" fw={500} mb={4}>
            {t('channels.environment')}
          </Text>
          <SegmentedControl
            value={draft.environment}
            onChange={(v) => set('environment', v as Draft['environment'])}
            data={(['test', 'production'] as const).map((v) => ({ value: v, label: t(`channels.environments.${v}`) }))}
          />
        </div>
        <TextInput
          label={t('channels.endpoint_url')}
          description={t('channels.endpoint_hint')}
          placeholder="https://"
          maxLength={300}
          required={draft.environment === 'production'}
          value={draft.endpoint_url}
          onChange={(e) => set('endpoint_url', e.currentTarget.value)}
          error={field('endpoint_url')}
        />
        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          <TextInput label={t('channels.account_code')} required maxLength={64} value={draft.account_code} onChange={(e) => set('account_code', e.currentTarget.value)} error={field('account_code')} />
          <TextInput label={t('channels.hotel_code')} required maxLength={64} value={draft.hotel_code} onChange={(e) => set('hotel_code', e.currentTarget.value)} error={field('hotel_code')} />
          <TextInput label={t('channels.username')} required maxLength={200} autoComplete="off" value={draft.username} onChange={(e) => set('username', e.currentTarget.value)} error={field('username')} />
          <PasswordInput
            label={t('channels.password')}
            required={!connection}
            placeholder={connection ? t('channels.password_unchanged') : undefined}
            maxLength={200}
            autoComplete="new-password"
            value={draft.password}
            onChange={(e) => set('password', e.currentTarget.value)}
            error={field('password')}
          />
        </SimpleGrid>
        <Text size="xs" c="dimmed">
          {t('channels.credentials_hint')}
        </Text>
        <Switch label={t('channels.push_ari')} checked={draft.push_ari} onChange={(e) => set('push_ari', e.currentTarget.checked)} />
        <Switch label={t('channels.pull_reservations')} description={t('channels.pull_hint')} checked={draft.pull_reservations} onChange={(e) => set('pull_reservations', e.currentTarget.checked)} />
        <SimpleGrid cols={{ base: 1, sm: 3 }}>
          <NumberInput label={t('channels.horizon_days')} min={30} max={750} value={draft.horizon_days} onChange={(v) => set('horizon_days', v)} error={field('horizon_days')} />
          <NumberInput label={t('channels.pull_interval')} min={120} max={300} step={30} value={draft.pull_interval_seconds} onChange={(v) => set('pull_interval_seconds', v)} error={field('pull_interval_seconds')} />
          <Select
            label={t('channels.rate_amount')}
            allowDeselect={false}
            value={draft.rate_amount}
            onChange={(v) => v && set('rate_amount', v as Draft['rate_amount'])}
            data={(['after_tax', 'before_tax'] as const).map((v) => ({ value: v, label: t(`channels.rate_amounts.${v}`) }))}
          />
        </SimpleGrid>
        <Group justify="flex-end">
          <Button variant="default" onClick={onCancel}>
            {t('common.cancel')}
          </Button>
          <SubmitButton loading={save.isPending} disabled={!required}>
            {t('common.save')}
          </SubmitButton>
        </Group>
      </Stack>
    </form>
  );
}
