import type { ReactNode } from 'react';
import { Badge, Box, Button, type ButtonProps, Center, Group, Stack, Text, Title, Tooltip } from '@mantine/core';
import { modals } from '@mantine/modals';
import { IconInbox } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { useConnectionStatus } from '@/api/realtime';
import i18n from '@/i18n';

export function PageHeader({ title, description, actions }: { title: ReactNode; description?: ReactNode; actions?: ReactNode }) {
  return (
    <Group justify="space-between" align="flex-end" mb="lg" wrap="wrap" gap="sm">
      <Box>
        <Title order={1}>{title}</Title>
        {description && (
          <Text c="dimmed" size="sm" mt={4} maw={720}>
            {description}
          </Text>
        )}
      </Box>
      {actions && <Group gap="xs">{actions}</Group>}
    </Group>
  );
}

export function SectionTitle({ children, description }: { children: ReactNode; description?: ReactNode }) {
  return (
    <Box mb="sm">
      <Title order={3}>{children}</Title>
      {description && (
        <Text size="sm" c="dimmed">
          {description}
        </Text>
      )}
    </Box>
  );
}

export function EmptyState({ title, description, action }: { title: ReactNode; description?: ReactNode; action?: ReactNode }) {
  return (
    <Center py={48}>
      <Stack align="center" gap="xs" maw={420}>
        <IconInbox size={40} stroke={1.3} color="var(--mantine-color-dimmed)" />
        <Text fw={600}>{title}</Text>
        {description && (
          <Text size="sm" c="dimmed" ta="center">
            {description}
          </Text>
        )}
        {action}
      </Stack>
    </Center>
  );
}

export function ActiveBadge({ active }: { active: boolean }) {
  const { t } = useTranslation();
  return (
    <Badge variant="light" color={active ? 'lagoon' : 'gray'} radius="sm">
      {active ? t('common.active') : t('common.inactive')}
    </Badge>
  );
}

/**
 * Submit button that is disabled while the server is unreachable: writes are
 * never queued offline (they could conflict with changes made meanwhile).
 */
export function SubmitButton({ children, ...props }: ButtonProps & { children: ReactNode; form?: string }) {
  const { t } = useTranslation();
  const status = useConnectionStatus();
  const offline = status === 'offline';
  const button = (
    <Button type="submit" {...props} disabled={props.disabled || offline}>
      {children}
    </Button>
  );
  return offline ? <Tooltip label={t('connection.writes_disabled')}>{button}</Tooltip> : button;
}

export function confirmDelete(opts: { title: string; message?: string; onConfirm: () => void | Promise<void> }) {
  modals.openConfirmModal({
    title: opts.title,
    children: <Text size="sm">{opts.message ?? i18n.t('common.delete_confirm')}</Text>,
    labels: { confirm: i18n.t('common.delete'), cancel: i18n.t('common.cancel') },
    confirmProps: { color: 'red' },
    onConfirm: () => void opts.onConfirm(),
  });
}
