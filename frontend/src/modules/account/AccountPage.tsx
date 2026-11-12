import { useState } from 'react';
import { Alert, Badge, Button, Card, Code, Group, PasswordInput, PinInput, Select, SimpleGrid, Stack, Table, Text, TextInput } from '@mantine/core';
import { useForm } from '@mantine/form';
import { IconShieldCheck } from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { api } from '@/api/client';
import type { Me, MySession } from '@/api/types';
import { useAuth } from '@/auth/AuthProvider';
import { PageHeader, SectionTitle, SubmitButton } from '@/components/ui';
import { LANGUAGES, type LanguageCode } from '@/i18n';
import { applyFieldErrors, notifyError, notifySuccess } from '@/lib/errors';
import { formatDateTime, formatRelative } from '@/lib/format';
import { describeAgent } from '@/modules/users/SessionsTab';

export default function AccountPage() {
  const { t } = useTranslation();
  return (
    <>
      <PageHeader title={t('account.title')} description={t('account.description')} />
      <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="lg">
        <Stack gap="lg">
          <ProfileCard />
          <PasswordCard />
        </Stack>
        <Stack gap="lg">
          <TwoFactorCard />
          <MySessionsCard />
        </Stack>
      </SimpleGrid>
    </>
  );
}

function ProfileCard() {
  const { t } = useTranslation();
  const { me, refresh, setLanguage } = useAuth();
  const form = useForm({ initialValues: { full_name: me?.user.full_name ?? '' } });
  const save = useMutation({ mutationFn: (body: { full_name: string }) => api.patch<Me>('/auth/me', body) });
  const submit = form.onSubmit(async (values) => {
    try {
      await save.mutateAsync(values);
      await refresh();
      notifySuccess(t('common.saved'));
    } catch (err) {
      if (!applyFieldErrors(err, form.setFieldError)) notifyError(err);
    }
  });
  return (
    <Card>
      <SectionTitle>{t('account.profile')}</SectionTitle>
      <form onSubmit={submit}>
        <Stack>
          <TextInput label={t('auth.email')} value={me?.user.email ?? ''} disabled />
          <TextInput label={t('users.full_name')} required {...form.getInputProps('full_name')} />
          <Select
            label={t('account.language')}
            description={t('account.language_hint')}
            allowDeselect={false}
            data={LANGUAGES.map((l) => ({ value: l.code, label: l.label }))}
            value={me?.user.preferred_language}
            onChange={(v) => v && setLanguage(v as LanguageCode).catch(notifyError)}
          />
          <Group justify="flex-end">
            <SubmitButton loading={save.isPending} disabled={!form.isDirty()}>
              {t('common.save')}
            </SubmitButton>
          </Group>
        </Stack>
      </form>
    </Card>
  );
}

function PasswordCard() {
  const { t } = useTranslation();
  const form = useForm({
    initialValues: { current_password: '', new_password: '', confirm: '' },
    validate: { confirm: (v, values) => (v === values.new_password ? null : t('validation.passwords_differ')) },
  });
  const change = useMutation({ mutationFn: (body: { current_password: string; new_password: string }) => api.post('/auth/me/password', body) });
  const submit = form.onSubmit(async ({ confirm: _confirm, ...values }) => {
    try {
      await change.mutateAsync(values);
      form.reset();
      notifySuccess(t('account.password_changed'));
    } catch (err) {
      if (!applyFieldErrors(err, form.setFieldError)) notifyError(err);
    }
  });
  return (
    <Card>
      <SectionTitle description={t('account.password_hint')}>{t('account.password')}</SectionTitle>
      <form onSubmit={submit}>
        <Stack>
          <PasswordInput label={t('account.current_password')} autoComplete="current-password" required {...form.getInputProps('current_password')} />
          <PasswordInput label={t('users.new_password')} description={t('users.password_policy')} autoComplete="new-password" required {...form.getInputProps('new_password')} />
          <PasswordInput label={t('account.confirm_password')} autoComplete="new-password" required {...form.getInputProps('confirm')} />
          <Group justify="flex-end">
            <SubmitButton loading={change.isPending}>{t('account.change_password')}</SubmitButton>
          </Group>
        </Stack>
      </form>
    </Card>
  );
}

function TwoFactorCard() {
  const { t } = useTranslation();
  const { me, refresh } = useAuth();
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const enabled = me?.user.totp_enabled;

  const begin = async () => {
    try {
      setSetup(await api.post('/auth/me/totp/setup'));
    } catch (err) {
      notifyError(err);
    }
  };
  const enable = async () => {
    try {
      await api.post('/auth/me/totp/enable', { code });
      setSetup(null);
      setCode('');
      await refresh();
      notifySuccess(t('account.2fa_enabled'));
    } catch {
      setError(t('errors.TOTP_INVALID'));
    }
  };
  const disable = async () => {
    try {
      await api.post('/auth/me/totp/disable', { password });
      setPassword('');
      await refresh();
      notifySuccess(t('account.2fa_disabled'));
    } catch (err) {
      notifyError(err);
    }
  };

  return (
    <Card>
      <Group justify="space-between" align="flex-start">
        <SectionTitle description={t('account.2fa_hint')}>{t('account.2fa')}</SectionTitle>
        <Badge color={enabled ? 'lagoon' : 'gray'} variant="light" leftSection={enabled ? <IconShieldCheck size={12} /> : null}>
          {enabled ? t('account.2fa_on') : t('account.2fa_off')}
        </Badge>
      </Group>
      {enabled ? (
        <Group align="flex-end">
          <PasswordInput label={t('account.current_password')} value={password} onChange={(e) => setPassword(e.currentTarget.value)} style={{ flex: 1 }} />
          <Button color="red" variant="light" onClick={disable} disabled={!password}>
            {t('account.2fa_disable')}
          </Button>
        </Group>
      ) : setup ? (
        <Stack>
          <Text size="sm">{t('account.2fa_step1')}</Text>
          <Code block style={{ wordBreak: 'break-all' }}>
            {setup.secret}
          </Code>
          <Text size="xs" c="dimmed" style={{ wordBreak: 'break-all' }}>
            {setup.otpauth_uri}
          </Text>
          <Text size="sm">{t('account.2fa_step2')}</Text>
          {error && (
            <Alert color="red" variant="light">
              {error}
            </Alert>
          )}
          <Group>
            <PinInput length={6} type="number" oneTimeCode value={code} onChange={(v) => { setCode(v); setError(null); }} />
            <Button onClick={enable} disabled={code.length !== 6}>
              {t('account.2fa_confirm')}
            </Button>
          </Group>
        </Stack>
      ) : (
        <Button variant="light" onClick={begin}>
          {t('account.2fa_enable')}
        </Button>
      )}
    </Card>
  );
}

function MySessionsCard() {
  const { t, i18n } = useTranslation();
  const { hotel } = useAuth();
  const qc = useQueryClient();
  const sessions = useQuery({ queryKey: ['me', 'sessions'], queryFn: () => api.get<MySession[]>('/auth/me/sessions') });
  const revoke = useMutation({
    mutationFn: (id: string) => api.delete(`/auth/me/sessions/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['me', 'sessions'] }),
  });
  return (
    <Card>
      <SectionTitle description={t('account.sessions_hint')}>{t('account.sessions')}</SectionTitle>
      <Table>
        <Table.Tbody>
          {sessions.data?.map((s) => (
            <Table.Tr key={s.id}>
              <Table.Td>
                <Text size="sm" fw={500}>
                  {s.device_label ?? describeAgent(s.user_agent)}
                </Text>
                <Text size="xs" c="dimmed">
                  {describeAgent(s.user_agent)} · {s.ip ?? '—'}
                </Text>
              </Table.Td>
              <Table.Td>
                <Text size="xs" c="dimmed" title={formatDateTime(s.last_seen_at, i18n.language, hotel?.timezone)}>
                  {formatRelative(s.last_seen_at, i18n.language)}
                </Text>
              </Table.Td>
              <Table.Td ta="right">
                {s.current ? (
                  <Badge variant="light">{t('sessions.this_device')}</Badge>
                ) : (
                  <Button size="xs" variant="subtle" color="red" onClick={() => revoke.mutate(s.id, { onError: notifyError })}>
                    {t('sessions.revoke')}
                  </Button>
                )}
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Card>
  );
}
