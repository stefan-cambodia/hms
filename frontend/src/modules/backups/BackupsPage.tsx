import { useEffect, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Card,
  Code,
  Group,
  List,
  Loader,
  Modal,
  PasswordInput,
  SimpleGrid,
  Stack,
  Table,
  Text,
  TextInput,
  ThemeIcon,
  Title,
  Tooltip,
} from '@mantine/core';
import { useForm } from '@mantine/form';
import { notifications } from '@mantine/notifications';
import { useQueryClient } from '@tanstack/react-query';
import {
  IconAlertTriangle,
  IconCircleCheck,
  IconCircleX,
  IconClockHour4,
  IconDatabaseExport,
  IconHistory,
  IconPlugConnectedX,
  IconRestore,
  IconShieldCheck,
} from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { api } from '@/api/client';
import { useHotelMutation, useHotelQuery } from '@/api/hooks';
import { hotelKey } from '@/api/realtime';
import type { BackupFile, BackupRun, BackupsStatus } from '@/api/types';
import { useAuth, useHotel } from '@/auth/AuthProvider';
import { EmptyState, PageHeader, SectionTitle } from '@/components/ui';
import { applyFieldErrors, notifyError, notifySuccess } from '@/lib/errors';
import { formatBytes, formatDateTime, formatRelative } from '@/lib/format';

/** hms-20261113T020000Z.dump → ISO instant (older files have no metadata). */
function fileInstant(file: string): string | null {
  const m = /^hms-(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z\.dump$/.exec(file);
  return m ? `${m[1]}-${m[2]}-${m[3]}T${m[4]}:${m[5]}:${m[6]}Z` : null;
}

function backupInstant(b: BackupFile): string | null {
  return b.created_at ?? fileInstant(b.file);
}

function useText() {
  const { t, i18n } = useTranslation();
  const known = (group: string, value: string | null | undefined) =>
    value && i18n.exists(`backups.${group}.${value}`) ? t(`backups.${group}.${value}`) : (value ?? '—');
  return { t, i18n, known };
}

export default function BackupsPage() {
  const { t, i18n, known } = useText();
  const hotel = useHotel();
  const qc = useQueryClient();
  const [restoring, setRestoring] = useState<BackupFile | null>(null);
  // Request ids sent from this screen: their outcome is announced when known.
  const [watching, setWatching] = useState<{ id: string; kind: 'backup' | 'restore' } | null>(null);
  const status = useHotelQuery<BackupsStatus>('backup', '/backups');
  const data = status.data;
  const busy = !!data && (data.current !== null || data.pending.length > 0);
  // Poll: the backup service reports through files, not through events.
  useEffect(() => {
    const ms = busy || watching ? 3000 : 30000;
    const id = window.setInterval(() => void qc.invalidateQueries({ queryKey: hotelKey(hotel.id, 'backup') }), ms);
    return () => window.clearInterval(id);
  }, [busy, watching, qc, hotel.id]);

  const backupNow = useHotelMutation<void, { request_id: string }>((h) => api.post(h('/backups')), ['backup']);
  // A restore's safety backup carries the restore's request id: match the kind too.
  const finished = watching ? data?.runs.find((r) => r.request_id === watching.id && r.kind === watching.kind) : undefined;
  useEffect(() => {
    if (!finished) return;
    if (finished.status !== 'ok') {
      notifications.show({ color: 'red', title: t('backups.failed_title'), message: known('run_errors', finished.error) });
      setWatching(null);
    } else if (finished.kind === 'backup') {
      notifySuccess(t('backups.backup_done'));
      setWatching(null);
    }
    // A successful restore stays announced on the page (reload button).
  }, [finished, t, known]);

  const service = data?.service;
  const lastOk = data?.backups.find((b) => b.trigger !== 'safety') ?? data?.backups[0];
  const lastOkAt = lastOk ? backupInstant(lastOk) : null;
  const ageHours = lastOkAt ? (Date.now() - new Date(lastOkAt).getTime()) / 3_600_000 : null;
  const overdue = ageHours !== null && service?.interval_hours ? ageHours > service.interval_hours * 2 : false;

  return (
    <>
      <PageHeader
        title={t('nav.backups')}
        description={t('backups.description')}
        actions={
          <Button
            leftSection={<IconDatabaseExport size={16} />}
            disabled={!service?.running || busy}
            loading={backupNow.isPending}
            onClick={() =>
              void backupNow.mutateAsync().then((r) => {
                setWatching({ id: r.request_id, kind: 'backup' });
                notifySuccess(t('backups.backup_requested'));
              }, notifyError)
            }
          >
            {t('backups.backup_now')}
          </Button>
        }
      />
      {status.isPending ? (
        <Loader size="sm" />
      ) : !data ? (
        <RestoreOutage watching={!!watching} />
      ) : (
        <Stack gap="lg">
          {!service?.connected ? (
            <Alert color="gray" icon={<IconPlugConnectedX size={18} />} title={t('backups.not_connected_title')}>
              {t('backups.not_connected_body')}
            </Alert>
          ) : (
            <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }}>
              <Tile
                label={t('backups.service')}
                icon={service.running ? IconCircleCheck : IconAlertTriangle}
                color={service.running ? 'teal' : 'red'}
                value={service.running ? t('backups.running') : t('backups.stopped')}
                hint={service.last_seen ? formatRelative(service.last_seen, i18n.language) : undefined}
              />
              <Tile
                label={t('backups.last_backup')}
                icon={!lastOkAt ? IconAlertTriangle : overdue ? IconClockHour4 : IconShieldCheck}
                color={!lastOkAt ? 'red' : overdue ? 'orange' : 'teal'}
                value={lastOkAt ? formatRelative(lastOkAt, i18n.language) : t('backups.none_yet')}
                hint={lastOkAt ? formatDateTime(lastOkAt, i18n.language, hotel.timezone) : undefined}
              />
              <Tile
                label={t('backups.next_backup')}
                icon={IconClockHour4}
                color="gray"
                value={service.next_scheduled ? formatDateTime(service.next_scheduled, i18n.language, hotel.timezone) : '—'}
                hint={service.interval_hours ? t('backups.every_hours', { hours: service.interval_hours }) : undefined}
              />
              <Tile
                label={t('backups.retention')}
                icon={IconHistory}
                color="gray"
                value={service.retention_days ? t('backups.days', { count: service.retention_days }) : '—'}
                hint={t('backups.retention_hint')}
              />
            </SimpleGrid>
          )}

          <Operation data={data} />
          {finished?.kind === 'restore' && finished.status === 'ok' && (
            <Alert color="teal" icon={<IconCircleCheck size={18} />} title={t('backups.restore_done_title')}>
              <Stack gap="xs" align="flex-start">
                <Text size="sm">{t('backups.restore_done_body')}</Text>
                <Button size="xs" onClick={() => window.location.reload()}>
                  {t('backups.reload')}
                </Button>
              </Stack>
            </Alert>
          )}

          <Stack gap="xs">
            <SectionTitle description={t('backups.list_hint')}>{t('backups.list')}</SectionTitle>
            {!data.restore.allowed && data.backups.length > 0 && (
              <Text size="sm" c="dimmed">
                {t(`backups.restore_reason.${data.restore.reason}`)}
              </Text>
            )}
            {data.backups.length === 0 ? (
              <EmptyState title={t('backups.empty')} />
            ) : (
              <BackupsTable data={data} onRestore={setRestoring} />
            )}
          </Stack>

          <Stack gap="xs">
            <SectionTitle>{t('backups.history')}</SectionTitle>
            {data.runs.length === 0 ? <EmptyState title={t('backups.no_runs')} /> : <RunsTable runs={data.runs} />}
          </Stack>
        </Stack>
      )}
      {restoring && (
        <RestoreModal
          backup={restoring}
          onClose={() => setRestoring(null)}
          onRequested={(id) => {
            setRestoring(null);
            setWatching({ id, kind: 'restore' });
          }}
        />
      )}
    </>
  );
}

function Tile({
  label,
  value,
  hint,
  icon: Icon,
  color,
}: {
  label: string;
  value: string;
  hint?: string;
  icon: typeof IconCircleCheck;
  color: string;
}) {
  return (
    <Card withBorder padding="md">
      <Group gap="sm" wrap="nowrap" align="flex-start">
        <ThemeIcon variant="light" color={color} size="lg" radius="md">
          <Icon size={20} />
        </ThemeIcon>
        <div style={{ minWidth: 0 }}>
          <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
            {label}
          </Text>
          <Text fw={700}>{value}</Text>
          {hint && (
            <Text size="xs" c="dimmed">
              {hint}
            </Text>
          )}
        </div>
      </Group>
    </Card>
  );
}

function Operation({ data }: { data: BackupsStatus }) {
  const { t, known } = useText();
  if (data.current) {
    const restore = data.current.kind === 'restore';
    return (
      <Alert color={restore ? 'orange' : 'blue'} icon={<Loader size={16} />} title={t(restore ? 'backups.restoring' : 'backups.backing_up')}>
        <Text size="sm">
          {known('steps', data.current.step)}
          {data.current.requested_by ? ` · ${data.current.requested_by}` : ''}
        </Text>
        {restore && (
          <Text size="sm" mt={4}>
            {t('backups.restoring_hint')}
          </Text>
        )}
      </Alert>
    );
  }
  if (data.pending.length > 0) {
    return (
      <Alert color="blue" icon={<Loader size={16} />} title={t('backups.waiting')}>
        {t(data.pending[0].kind === 'restore' ? 'backups.waiting_restore' : 'backups.waiting_backup')}
      </Alert>
    );
  }
  return null;
}

/** While the database is being switched the API itself is unreachable. */
function RestoreOutage({ watching }: { watching: boolean }) {
  const { t } = useText();
  return (
    <Alert color={watching ? 'orange' : 'red'} icon={watching ? <Loader size={16} /> : <IconAlertTriangle size={18} />} title={t(watching ? 'backups.restoring' : 'common.error')}>
      {t(watching ? 'backups.restoring_hint' : 'backups.load_failed')}
    </Alert>
  );
}

function BackupsTable({ data, onRestore }: { data: BackupsStatus; onRestore: (b: BackupFile) => void }) {
  const { t, i18n, known } = useText();
  const hotel = useHotel();
  const busy = data.current !== null || data.pending.length > 0;
  return (
    <Table.ScrollContainer minWidth={820}>
      <Table verticalSpacing={6} data-testid="backups-table">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{t('backups.date')}</Table.Th>
            <Table.Th>{t('backups.origin')}</Table.Th>
            <Table.Th ta="right">{t('backups.size')}</Table.Th>
            <Table.Th>{t('backups.verification')}</Table.Th>
            <Table.Th>{t('backups.checksum')}</Table.Th>
            <Table.Th />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {data.backups.map((b) => {
            const at = backupInstant(b);
            const blocked = !b.restorable ? t('backups.other_version') : busy ? t('backups.busy') : !data.service.running ? t('backups.stopped') : null;
            return (
              <Table.Tr key={b.file}>
                <Table.Td>
                  <Text size="sm" fw={600}>
                    {at ? formatDateTime(at, i18n.language, hotel.timezone) : b.file}
                  </Text>
                  <Text size="xs" c="dimmed">
                    {b.file}
                  </Text>
                </Table.Td>
                <Table.Td style={{ whiteSpace: 'nowrap' }}>
                  <Badge variant="light" color={b.trigger === 'safety' ? 'orange' : 'gray'} styles={{ label: { overflow: 'visible' } }}>
                    {known('triggers', b.trigger)}
                  </Badge>
                  {b.requested_by && (
                    <Text size="xs" c="dimmed">
                      {b.requested_by}
                    </Text>
                  )}
                </Table.Td>
                <Table.Td ta="right" className="hms-num" style={{ whiteSpace: 'nowrap' }}>
                  {formatBytes(b.bytes, i18n.language)}
                </Table.Td>
                <Table.Td>
                  {b.verified_tables != null ? (
                    <Group gap={4} wrap="nowrap">
                      <IconShieldCheck size={16} color="var(--mantine-color-teal-6)" aria-hidden />
                      <Text size="sm">{t('backups.verified', { tables: b.verified_tables, hotels: b.verified_hotels ?? 0 })}</Text>
                    </Group>
                  ) : (
                    '—'
                  )}
                </Table.Td>
                <Table.Td>
                  {b.sha256 ? (
                    <Tooltip label={b.sha256}>
                      <Code>{b.sha256.slice(0, 12)}…</Code>
                    </Tooltip>
                  ) : (
                    '—'
                  )}
                </Table.Td>
                <Table.Td style={{ whiteSpace: 'nowrap' }}>
                  {data.restore.allowed && (
                    <Tooltip label={blocked} disabled={!blocked} multiline w={260}>
                      <span>
                        <Button size="xs" variant="light" color="red" leftSection={<IconRestore size={14} />} disabled={!!blocked} onClick={() => onRestore(b)} styles={{ label: { overflow: 'visible' } }}>
                          {t('backups.restore')}
                        </Button>
                      </span>
                    </Tooltip>
                  )}
                </Table.Td>
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}

function RunsTable({ runs }: { runs: BackupRun[] }) {
  const { t, i18n, known } = useText();
  const hotel = useHotel();
  return (
    <Table.ScrollContainer minWidth={760}>
      <Table verticalSpacing={6} data-testid="backup-runs">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{t('backups.started')}</Table.Th>
            <Table.Th>{t('backups.operation')}</Table.Th>
            <Table.Th>{t('backups.origin')}</Table.Th>
            <Table.Th>{t('backups.result')}</Table.Th>
            <Table.Th ta="right">{t('backups.duration')}</Table.Th>
            <Table.Th>{t('backups.detail')}</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {runs.map((r, i) => {
            const seconds = r.started_at && r.finished_at ? Math.max(0, Math.round((new Date(r.finished_at).getTime() - new Date(r.started_at).getTime()) / 1000)) : null;
            const ok = r.status === 'ok';
            return (
              <Table.Tr key={`${r.started_at}-${i}`}>
                <Table.Td>{formatDateTime(r.started_at, i18n.language, hotel.timezone)}</Table.Td>
                <Table.Td>{known('kinds', r.kind)}</Table.Td>
                <Table.Td>
                  <Text size="sm">{known('triggers', r.trigger)}</Text>
                  {r.requested_by && (
                    <Text size="xs" c="dimmed">
                      {r.requested_by}
                    </Text>
                  )}
                </Table.Td>
                <Table.Td>
                  <Badge variant="light" color={ok ? 'teal' : 'red'} leftSection={ok ? <IconCircleCheck size={12} /> : <IconCircleX size={12} />}>
                    {t(ok ? 'backups.ok' : 'backups.failed')}
                  </Badge>
                </Table.Td>
                <Table.Td ta="right" className="hms-num">
                  {seconds != null ? t('backups.duration_s', { value: seconds }) : '—'}
                </Table.Td>
                <Table.Td maw={360}>
                  <Text size="sm" lineClamp={2}>
                    {ok
                      ? [r.file, r.safety_backup && t('backups.safety_backup_named', { file: r.safety_backup })].filter(Boolean).join(' · ')
                      : known('run_errors', r.error)}
                  </Text>
                </Table.Td>
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}

function RestoreModal({ backup, onClose, onRequested }: { backup: BackupFile; onClose: () => void; onRequested: (requestId: string) => void }) {
  const { t, i18n } = useText();
  const hotel = useHotel();
  const { me } = useAuth();
  const totp = !!me?.user.totp_enabled;
  const at = backupInstant(backup);
  const form = useForm({ initialValues: { password: '', totp_code: '', confirmation: '' } });
  const restore = useHotelMutation<typeof form.values, { request_id: string }>(
    (h, v) => api.post(h('/backups/restore'), { file: backup.file, password: v.password, totp_code: totp ? v.totp_code : null, confirmation: v.confirmation }),
    ['backup'],
  );
  const confirmed = form.values.confirmation.trim().toUpperCase() === hotel.code.toUpperCase();
  return (
    <Modal opened onClose={onClose} title={<Title order={4}>{t('backups.restore_title')}</Title>} size="lg">
      <form
        onSubmit={form.onSubmit((v) =>
          void restore.mutateAsync(v).then(
            (r) => {
              notifySuccess(t('backups.restore_requested'));
              onRequested(r.request_id);
            },
            (e) => {
              if (!applyFieldErrors(e, form.setFieldError)) notifyError(e);
            },
          ),
        )}
      >
        <Stack>
          <Alert color="red" icon={<IconAlertTriangle size={18} />}>
            <Text size="sm" fw={600}>
              {t('backups.restore_what', { date: at ? formatDateTime(at, i18n.language, hotel.timezone) : backup.file })}
            </Text>
            <List size="sm" mt="xs" spacing={4}>
              <List.Item>{t('backups.restore_lost')}</List.Item>
              <List.Item>{t('backups.restore_safety')}</List.Item>
              <List.Item>{t('backups.restore_downtime')}</List.Item>
              <List.Item>{t('backups.restore_channels')}</List.Item>
            </List>
          </Alert>
          <PasswordInput label={t('backups.your_password')} autoComplete="current-password" required {...form.getInputProps('password')} />
          {totp && <TextInput label={t('auth.totp_prompt')} inputMode="numeric" autoComplete="one-time-code" required {...form.getInputProps('totp_code')} />}
          <TextInput
            label={t('backups.type_code', { code: hotel.code })}
            autoComplete="off"
            required
            {...form.getInputProps('confirmation')}
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" color="red" leftSection={<IconRestore size={16} />} disabled={!confirmed} loading={restore.isPending}>
              {t('backups.restore_confirm')}
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}
