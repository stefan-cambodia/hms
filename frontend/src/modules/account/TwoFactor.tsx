import { useState } from 'react';
import { Alert, Badge, Box, Button, Card, Center, Checkbox, Code, CopyButton, Group, Image, Modal, Paper, PasswordInput, PinInput, SimpleGrid, Stack, Text, Title } from '@mantine/core';
import { IconCheck, IconCopy, IconDownload, IconLogout, IconPrinter, IconShieldCheck, IconShieldLock } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { api, ApiError } from '@/api/client';
import { HotelIcon } from '@/app/navigation';
import { useAuth } from '@/auth/AuthProvider';
import { LanguageSwitcher } from '@/components/LanguageSwitcher';
import { SectionTitle } from '@/components/ui';
import { errorMessage, notifyError, notifySuccess } from '@/lib/errors';

interface TotpSetup {
  secret: string;
  otpauth_uri: string;
  qr_svg: string;
}

/** Scan the QR code (or type the key), confirm a code: two-factor is on and the recovery codes are shown. */
export function TwoFactorSetup({ onDone }: { onDone?: () => void }) {
  const { t } = useTranslation();
  const { refresh } = useAuth();
  const [setup, setSetup] = useState<TotpSetup | null>(null);
  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [codes, setCodes] = useState<string[] | null>(null);
  const [busy, setBusy] = useState(false);

  const begin = async () => {
    setBusy(true);
    try {
      setSetup(await api.post<TotpSetup>('/auth/me/totp/setup'));
    } catch (err) {
      notifyError(err);
    } finally {
      setBusy(false);
    }
  };
  const enable = async () => {
    setBusy(true);
    try {
      const r = await api.post<{ codes: string[] }>('/auth/me/totp/enable', { code });
      setCodes(r.codes);
    } catch (err) {
      setCode('');
      setError(err instanceof ApiError && err.code === 'TOTP_INVALID' ? t('errors.TOTP_INVALID') : errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  const finish = async () => {
    setCodes(null);
    setSetup(null);
    setCode('');
    await refresh();
    notifySuccess(t('account.2fa_enabled'));
    onDone?.();
  };

  if (!setup)
    return (
      <Button variant="light" leftSection={<IconShieldLock size={16} />} onClick={begin} loading={busy}>
        {t('account.2fa_enable')}
      </Button>
    );
  return (
    <Stack>
      <Text size="sm">{t('account.2fa_step1')}</Text>
      <Group align="flex-start" gap="lg" wrap="wrap">
        <Paper withBorder p={4} radius="md" bg="white">
          <Image src={setup.qr_svg} alt={t('account.2fa_qr')} w={180} h={180} data-testid="totp-qr" />
        </Paper>
        <Stack gap={4} style={{ flex: 1, minWidth: 200 }}>
          <Text size="xs" c="dimmed">
            {t('account.2fa_manual_key')}
          </Text>
          <Code block style={{ wordBreak: 'break-all', letterSpacing: '0.08em' }} data-testid="totp-secret">
            {setup.secret.replace(/(.{4})/g, '$1 ').trim()}
          </Code>
        </Stack>
      </Group>
      <Text size="sm">{t('account.2fa_step2')}</Text>
      {error && (
        <Alert color="red" variant="light">
          {error}
        </Alert>
      )}
      <Group>
        <PinInput length={6} type="number" oneTimeCode value={code} onChange={(v) => { setCode(v); setError(null); }} aria-label={t('auth.totp_prompt')} />
        <Button onClick={enable} disabled={code.length !== 6} loading={busy}>
          {t('account.2fa_confirm')}
        </Button>
      </Group>
      {codes && <RecoveryCodesModal codes={codes} onClose={() => void finish()} />}
    </Stack>
  );
}

/** Shown once: the codes cannot be displayed again, only replaced. */
export function RecoveryCodesModal({ codes, onClose }: { codes: string[]; onClose: () => void }) {
  const { t } = useTranslation();
  const { me } = useAuth();
  const [saved, setSaved] = useState(false);
  const text = `${t('account.recovery_file_title', { email: me?.user.email ?? '' })}\n\n${codes.join('\n')}\n\n${t('account.recovery_file_hint')}\n`;

  const download = () => {
    const url = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }));
    const a = Object.assign(document.createElement('a'), { href: url, download: 'hms-recovery-codes.txt' });
    a.click();
    URL.revokeObjectURL(url);
  };
  const print = () => {
    const w = window.open('', '_blank', 'width=480,height=640');
    if (!w) return;
    const pre = w.document.createElement('pre');
    pre.style.font = '16px/1.8 monospace';
    pre.textContent = text;
    w.document.body.appendChild(pre);
    w.print();
  };

  return (
    <Modal opened onClose={() => saved && onClose()} withCloseButton={false} closeOnClickOutside={false} closeOnEscape={false} title={t('account.recovery_title')} size="md" centered>
      <Stack>
        <Text size="sm">{t('account.recovery_hint')}</Text>
        <SimpleGrid cols={2} spacing={6} data-testid="recovery-codes">
          {codes.map((c) => (
            <Code key={c} ta="center" fz="md" py={6} style={{ letterSpacing: '0.06em' }}>
              {c}
            </Code>
          ))}
        </SimpleGrid>
        <Group gap="xs">
          <CopyButton value={codes.join('\n')}>
            {({ copied, copy }) => (
              <Button size="xs" variant="default" leftSection={copied ? <IconCheck size={14} /> : <IconCopy size={14} />} onClick={copy}>
                {copied ? t('account.recovery_copied') : t('account.recovery_copy')}
              </Button>
            )}
          </CopyButton>
          <Button size="xs" variant="default" leftSection={<IconDownload size={14} />} onClick={download}>
            {t('account.recovery_download')}
          </Button>
          <Button size="xs" variant="default" leftSection={<IconPrinter size={14} />} onClick={print}>
            {t('account.recovery_print')}
          </Button>
        </Group>
        <Checkbox label={t('account.recovery_saved')} checked={saved} onChange={(e) => setSaved(e.currentTarget.checked)} />
        <Group justify="flex-end">
          <Button onClick={onClose} disabled={!saved}>
            {t('common.done')}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

/** My account: two-factor status, recovery codes left, new codes, turn off. */
export function TwoFactorCard() {
  const { t } = useTranslation();
  const { me, refresh } = useAuth();
  const [password, setPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [codes, setCodes] = useState<string[] | null>(null);
  const enabled = !!me?.user.totp_enabled;
  const required = !!me?.two_factor_required;
  const left = me?.recovery_codes_left ?? 0;

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
  const regenerate = async () => {
    try {
      const r = await api.post<{ codes: string[] }>('/auth/me/recovery-codes', { password: newPassword });
      setNewPassword('');
      setCodes(r.codes);
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
      {required && (
        <Text size="sm" c="dimmed" mb="sm">
          {t('account.2fa_required_by_role')}
        </Text>
      )}
      {!enabled ? (
        <TwoFactorSetup />
      ) : (
        <Stack>
          <Box data-testid="recovery-status">
            <Text size="sm" fw={600}>
              {t('account.recovery_left', { n: left })}
            </Text>
            <Text size="xs" c={left <= 3 ? 'red' : 'dimmed'}>
              {left <= 3 ? t('account.recovery_low') : t('account.recovery_left_hint')}
            </Text>
          </Box>
          <Group align="flex-end">
            <PasswordInput label={t('account.current_password')} value={newPassword} onChange={(e) => setNewPassword(e.currentTarget.value)} style={{ flex: 1 }} />
            <Button variant="light" onClick={regenerate} disabled={!newPassword}>
              {t('account.recovery_regenerate')}
            </Button>
          </Group>
          {!required && (
            <Group align="flex-end">
              <PasswordInput label={t('account.current_password')} value={password} onChange={(e) => setPassword(e.currentTarget.value)} style={{ flex: 1 }} />
              <Button color="red" variant="light" onClick={disable} disabled={!password}>
                {t('account.2fa_disable')}
              </Button>
            </Group>
          )}
        </Stack>
      )}
      {codes && (
        <RecoveryCodesModal
          codes={codes}
          onClose={() => {
            setCodes(null);
            void refresh();
          }}
        />
      )}
    </Card>
  );
}

/** The whole screen while a role requires two-factor that is not set up yet. */
export function TwoFactorRequiredPage() {
  const { t } = useTranslation();
  const { me, logout } = useAuth();
  return (
    <Box mih="100dvh" style={{ background: 'var(--hms-login-bg)' }}>
      <Group justify="space-between" p="md">
        <Group gap="xs">
          <HotelIcon size={26} stroke={1.6} />
          <Text fw={650}>{me?.user.full_name}</Text>
        </Group>
        <Group gap="xs">
          <LanguageSwitcher />
          <Button variant="subtle" color="gray" leftSection={<IconLogout size={16} />} onClick={() => void logout()}>
            {t('auth.logout')}
          </Button>
        </Group>
      </Group>
      <Center px="md" pb={64}>
        <Paper w="100%" maw={620} p="xl" shadow="md" withBorder data-testid="two-factor-required">
          <Stack>
            <Group gap="sm">
              <IconShieldLock size={30} stroke={1.5} color="var(--mantine-color-lagoon-7)" />
              <Title order={2}>{t('account.2fa_required_title')}</Title>
            </Group>
            <Text size="sm">{t('account.2fa_required_body')}</Text>
            <TwoFactorSetup />
          </Stack>
        </Paper>
      </Center>
    </Box>
  );
}
