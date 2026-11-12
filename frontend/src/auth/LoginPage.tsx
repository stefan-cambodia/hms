import { useState } from 'react';
import { Alert, Box, Button, Center, Group, Paper, PasswordInput, PinInput, Stack, Text, TextInput, Title } from '@mantine/core';
import { useForm } from '@mantine/form';
import { IconAlertCircle, IconLock } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { ApiError } from '@/api/client';
import { HotelIcon } from '@/app/navigation';
import { useAuth } from '@/auth/AuthProvider';
import { LanguageSwitcher } from '@/components/LanguageSwitcher';
import { errorMessage } from '@/lib/errors';

export function LoginPage() {
  const { t } = useTranslation();
  const { login } = useAuth();
  const [needTotp, setNeedTotp] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const form = useForm({
    initialValues: { email: '', password: '', totp_code: '' },
    validate: {
      email: (v) => (/^\S+@\S+\.\S+$/.test(v) ? null : t('validation.email')),
      password: (v) => (v ? null : t('validation.required')),
    },
  });

  const submit = form.onSubmit(async (values) => {
    setBusy(true);
    setError(null);
    try {
      await login({ email: values.email.trim(), password: values.password, totp_code: needTotp ? values.totp_code : undefined });
    } catch (err) {
      if (err instanceof ApiError && err.code === 'TOTP_REQUIRED') {
        setNeedTotp(true);
      } else {
        if (err instanceof ApiError && err.code === 'TOTP_INVALID') form.setFieldValue('totp_code', '');
        setError(errorMessage(err));
      }
    } finally {
      setBusy(false);
    }
  });

  return (
    <Box mih="100dvh" style={{ background: 'var(--hms-login-bg)' }}>
      <Group justify="flex-end" p="md">
        <LanguageSwitcher />
      </Group>
      <Center px="md" pb={64} mih="calc(100dvh - 72px)">
        <Paper w="100%" maw={420} p="xl" shadow="md" withBorder>
          <Stack gap="lg">
            <Stack gap={6} align="center">
              <HotelIcon size={40} stroke={1.4} />
              <Title order={2} ta="center">
                {t('auth.title')}
              </Title>
              <Text size="sm" c="dimmed" ta="center">
                {t('auth.subtitle')}
              </Text>
            </Stack>
            {error && (
              <Alert color="red" variant="light" icon={<IconAlertCircle size={18} />}>
                {error}
              </Alert>
            )}
            <form onSubmit={submit} noValidate>
              <Stack gap="md">
                <TextInput label={t('auth.email')} type="email" autoComplete="username" autoFocus size="md" {...form.getInputProps('email')} disabled={needTotp} />
                <PasswordInput label={t('auth.password')} autoComplete="current-password" size="md" {...form.getInputProps('password')} disabled={needTotp} />
                {needTotp && (
                  <Stack gap={6} align="center">
                    <Text size="sm" fw={500}>
                      {t('auth.totp_prompt')}
                    </Text>
                    <PinInput length={6} type="number" oneTimeCode autoFocus size="md" {...form.getInputProps('totp_code')} />
                  </Stack>
                )}
                <Button type="submit" size="md" loading={busy} leftSection={<IconLock size={18} />} fullWidth>
                  {t('auth.sign_in')}
                </Button>
              </Stack>
            </form>
          </Stack>
        </Paper>
      </Center>
    </Box>
  );
}
