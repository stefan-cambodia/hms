import { useState } from 'react';
import { useSearchParams } from 'react-router';
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  Divider,
  Drawer,
  Group,
  Loader,
  Modal,
  Pagination,
  SegmentedControl,
  Select,
  Stack,
  Switch,
  Table,
  Text,
  Textarea,
  TextInput,
  Timeline,
  Title,
} from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import { useDebouncedValue } from '@mantine/hooks';
import { IconAlertTriangle, IconPlus, IconSearch } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { api } from '@/api/client';
import { useHotelMutation, useHotelQuery } from '@/api/hooks';
import type { MaintenanceDetail, MaintenanceRequest, MaintenanceStatus, Page, Priority, StaffMember } from '@/api/types';
import { useAuth, useHotel } from '@/auth/AuthProvider';
import { EmptyState, PageHeader, SubmitButton } from '@/components/ui';
import { addDays } from '@/lib/dates';
import { errorMessage, notifyError, notifySuccess } from '@/lib/errors';
import { formatDate, formatDateTime } from '@/lib/format';
import { useHotelToday } from '@/modules/reservations/shared';
import { MaintenanceStatusBadge, PRIORITIES, PriorityBadge, ReportIssueModal, useWhere } from './shared';

const PAGE = 50;
const ENTITIES = ['maintenance_request', 'room_board', 'calendar', 'housekeeping_task'];

export default function MaintenancePage() {
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const where = useWhere();
  const [params, setParams] = useSearchParams();
  const [state, setState] = useState<'open' | 'closed' | 'all'>('open');
  const [priority, setPriority] = useState<string | null>(null);
  const [mine, setMine] = useState(false);
  const [search, setSearch] = useState('');
  const [q] = useDebouncedValue(search, 250);
  const [page, setPage] = useState(1);
  const [reporting, setReporting] = useState(false);
  const selected = params.get('id');
  const select = (id: string | null) =>
    setParams(
      (p) => {
        const out = new URLSearchParams(p);
        if (id) out.set('id', id);
        else out.delete('id');
        return out;
      },
      { replace: true },
    );
  const list = useHotelQuery<Page<MaintenanceRequest>>('maintenance_request', '/maintenance-requests', {
    state,
    priority,
    assigned_to: mine ? 'me' : undefined,
    q,
    limit: PAGE,
    offset: (page - 1) * PAGE,
  });

  return (
    <>
      <PageHeader
        title={t('nav.maintenance')}
        description={t('maintenance.description')}
        actions={
          can('maintenance.report') && (
            <Button leftSection={<IconPlus size={16} />} onClick={() => setReporting(true)}>
              {t('maintenance.report')}
            </Button>
          )
        }
      />
      <Card mb="md" padding="sm">
        <Group gap="sm" wrap="wrap">
          <SegmentedControl
            value={state}
            onChange={(v) => {
              setState(v as typeof state);
              setPage(1);
            }}
            data={(['open', 'closed', 'all'] as const).map((s) => ({ value: s, label: t(`maintenance.states.${s}`) }))}
          />
          <Select placeholder={t('maintenance.priority')} clearable w={150} data={PRIORITIES.map((p) => ({ value: p, label: t(`maintenance.priorities.${p}`) }))} value={priority} onChange={setPriority} />
          <TextInput leftSection={<IconSearch size={16} />} placeholder={t('maintenance.search')} value={search} onChange={(e) => setSearch(e.currentTarget.value)} w={260} />
          {can('maintenance.manage') && <Switch label={t('maintenance.assigned_to_me')} checked={mine} onChange={(e) => setMine(e.currentTarget.checked)} />}
          {list.isFetching && <Loader size="xs" />}
        </Group>
      </Card>
      {list.data && list.data.items.length === 0 ? (
        <EmptyState title={t(state === 'open' ? 'maintenance.empty_open' : 'maintenance.empty')} />
      ) : (
        <Card padding={0}>
          <div className="hms-table-wrap">
            <Table highlightOnHover verticalSpacing="sm" miw={680}>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t('maintenance.request')}</Table.Th>
                  <Table.Th>{t('maintenance.where')}</Table.Th>
                  <Table.Th>{t('maintenance.priority')}</Table.Th>
                  <Table.Th>{t('common.status')}</Table.Th>
                  <Table.Th visibleFrom="md">{t('maintenance.assigned_to')}</Table.Th>
                  <Table.Th visibleFrom="md">{t('maintenance.reported')}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {list.data?.items.map((r) => (
                  <Table.Tr key={r.id} style={{ cursor: 'pointer' }} onClick={() => select(r.id)} data-request={r.number}>
                    <Table.Td>
                      <Text size="sm" fw={600}>
                        {r.title}
                      </Text>
                      <Text size="xs" c="dimmed">
                        {r.number} · {t(`maintenance.categories.${r.category}`)}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm">{where(r)}</Text>
                      {r.block && (
                        <Badge size="xs" color="gray" variant="filled" leftSection={<IconAlertTriangle size={10} />}>
                          {t('maintenance.out_until', { date: formatDate(r.block.end_date, i18n.language) })}
                        </Badge>
                      )}
                    </Table.Td>
                    <Table.Td>
                      <PriorityBadge priority={r.priority} />
                    </Table.Td>
                    <Table.Td>
                      <MaintenanceStatusBadge status={r.status} />
                    </Table.Td>
                    <Table.Td visibleFrom="md">
                      <Text size="sm">{r.assigned_to_name ?? '—'}</Text>
                    </Table.Td>
                    <Table.Td visibleFrom="md">
                      <Text size="sm">{formatDate(r.created_at.slice(0, 10), i18n.language)}</Text>
                      <Text size="xs" c="dimmed">
                        {r.reported_by_name ?? '—'}
                      </Text>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </div>
        </Card>
      )}
      {list.data && list.data.total > PAGE && <Pagination mt="md" total={Math.ceil(list.data.total / PAGE)} value={page} onChange={setPage} />}
      {reporting && <ReportIssueModal onClose={() => setReporting(false)} onCreated={(r) => select(r.id)} />}
      <Drawer opened={!!selected} onClose={() => select(null)} position="right" size="lg" title={<Title order={3}>{t('maintenance.request')}</Title>}>
        {selected && <RequestDetail id={selected} />}
      </Drawer>
    </>
  );
}

const NEXT: Record<MaintenanceStatus, MaintenanceStatus[]> = {
  reported: ['in_progress', 'on_hold', 'completed', 'cancelled'],
  in_progress: ['on_hold', 'completed', 'cancelled'],
  on_hold: ['in_progress', 'completed', 'cancelled'],
  completed: ['reported'],
  cancelled: ['reported'],
};

function RequestDetail({ id }: { id: string }) {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const { can } = useAuth();
  const where = useWhere();
  const today = useHotelToday();
  const manage = can('maintenance.manage');
  const detail = useHotelQuery<MaintenanceDetail>('maintenance_request', `/maintenance-requests/${id}`);
  const techs = useHotelQuery<StaffMember[]>('maintenance_request', '/maintenance/technicians', undefined, manage);
  const [comment, setComment] = useState('');
  const [closing, setClosing] = useState<MaintenanceStatus | null>(null);
  const [blocking, setBlocking] = useState(false);
  const post = useHotelMutation<{ path: string; body: Record<string, unknown> }, MaintenanceDetail>(
    (h, { path, body }) => api.post<MaintenanceDetail>(h(`/maintenance-requests/${id}${path}`), body),
    ENTITIES,
  );
  const patch = useHotelMutation<Record<string, unknown>, MaintenanceDetail>((h, body) => api.patch<MaintenanceDetail>(h(`/maintenance-requests/${id}`), body), ENTITIES);
  const r = detail.data;
  if (!r) return <Loader size="sm" />;
  const run = (path: string, body: Record<string, unknown>, done: string) => post.mutateAsync({ path, body }).then(() => notifySuccess(done), notifyError);
  const edit = (body: Record<string, unknown>) => patch.mutateAsync({ version: r.version, ...body }).then(() => notifySuccess(t('common.saved')), notifyError);
  const open = ['reported', 'in_progress', 'on_hold'].includes(r.status);

  return (
    <Stack data-testid="maintenance-detail">
      <Group justify="space-between" align="flex-start">
        <div>
          <Text fw={700} size="lg">
            {r.title}
          </Text>
          <Text size="sm" c="dimmed">
            {r.number} · {where(r)} · {t(`maintenance.categories.${r.category}`)}
          </Text>
        </div>
        <Group gap={6}>
          <PriorityBadge priority={r.priority} />
          <MaintenanceStatusBadge status={r.status} />
        </Group>
      </Group>
      {r.description && (
        <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>
          {r.description}
        </Text>
      )}
      {r.resolution && (
        <Alert color="teal" p="sm" title={t('maintenance.resolution')}>
          <Text size="sm">{r.resolution}</Text>
        </Alert>
      )}

      {r.room_id && (
        <Card withBorder padding="sm">
          {r.block ? (
            <Group justify="space-between" wrap="wrap">
              <Text size="sm" fw={600} c="red.7">
                {t('maintenance.room_out', { from: formatDate(r.block.start_date, i18n.language), until: formatDate(r.block.end_date, i18n.language) })}
              </Text>
              {manage && open && (
                <Group gap="xs">
                  <Button size="xs" variant="default" onClick={() => setBlocking(true)}>
                    {t('maintenance.change_dates')}
                  </Button>
                  <Button size="xs" variant="light" color="teal" loading={post.isPending} onClick={() => void run('/release', { version: r.version }, t('maintenance.back_in_service_done'))}>
                    {t('maintenance.back_in_service')}
                  </Button>
                </Group>
              )}
            </Group>
          ) : (
            <Group justify="space-between" wrap="wrap">
              <Text size="sm" c="dimmed">
                {t('maintenance.room_in_service')}
              </Text>
              {manage && open && (
                <Button size="xs" variant="light" color="red" onClick={() => setBlocking(true)}>
                  {t('maintenance.take_out_of_service')}
                </Button>
              )}
            </Group>
          )}
        </Card>
      )}

      {manage && (
        <Group grow align="flex-end">
          <Select
            label={t('maintenance.assigned_to')}
            clearable
            data={(techs.data ?? []).map((u) => ({ value: u.id, label: u.full_name }))}
            value={r.assigned_to}
            onChange={(v) => void edit({ assigned_to: v })}
          />
          <Select
            label={t('maintenance.priority')}
            allowDeselect={false}
            data={PRIORITIES.map((p) => ({ value: p, label: t(`maintenance.priorities.${p}`) }))}
            value={r.priority}
            onChange={(v) => v && v !== r.priority && void edit({ priority: v as Priority })}
          />
        </Group>
      )}
      {manage && (
        <Group gap="xs" wrap="wrap">
          {NEXT[r.status].map((s) => (
            <Button
              key={s}
              size="xs"
              variant={s === 'completed' ? 'filled' : s === 'cancelled' ? 'light' : 'default'}
              color={s === 'completed' ? 'teal' : s === 'cancelled' ? 'red' : undefined}
              loading={post.isPending}
              onClick={() => (s === 'completed' || s === 'cancelled' ? setClosing(s) : void run('/status', { version: r.version, status: s }, t('common.saved')))}
            >
              {t(`maintenance.actions.${s}`)}
            </Button>
          ))}
        </Group>
      )}

      <Divider label={t('maintenance.history')} labelPosition="left" />
      {can('maintenance.report') && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!comment.trim()) return;
            void post.mutateAsync({ path: '/comments', body: { comment: comment.trim() } }).then(() => setComment(''), notifyError);
          }}
        >
          <Group align="flex-end" wrap="nowrap">
            <Textarea style={{ flex: 1 }} autosize minRows={1} placeholder={t('maintenance.comment_placeholder')} value={comment} onChange={(e) => setComment(e.currentTarget.value)} maxLength={5000} />
            <SubmitButton size="sm" variant="light" loading={post.isPending} disabled={!comment.trim()}>
              {t('maintenance.add_comment')}
            </SubmitButton>
          </Group>
        </form>
      )}
      <Timeline bulletSize={14} lineWidth={2} active={r.updates.length}>
        {[...r.updates].reverse().map((u) => (
          <Timeline.Item key={u.id} title={<Text size="sm" fw={500}>{describeUpdate(u, t, i18n.language)}</Text>}>
            {u.comment && (
              <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>
                {u.comment}
              </Text>
            )}
            <Text size="xs" c="dimmed">
              {formatDateTime(u.at, i18n.language, hotel.timezone)} · {u.user_name ?? t('audit.system')}
            </Text>
          </Timeline.Item>
        ))}
      </Timeline>

      {closing && <CloseModal request={r} status={closing} onClose={() => setClosing(null)} onDone={() => setClosing(null)} />}
      {blocking && <BlockModal request={r} today={today} onClose={() => setBlocking(false)} />}
    </Stack>
  );
}

function describeUpdate(u: MaintenanceDetail['updates'][number], t: ReturnType<typeof useTranslation>['t'], language: string): string {
  const d = u.details as Record<string, string | boolean | string[] | null>;
  switch (u.action) {
    case 'status': {
      let text = t('maintenance.events.status', { from: t(`maintenance.statuses.${d.from}`), to: t(`maintenance.statuses.${d.to}`) });
      if (d.room_released) text += ` · ${t('maintenance.events.room_released')}`;
      if (d.cleaning_requested) text += ` · ${t('maintenance.events.cleaning_requested')}`;
      return text;
    }
    case 'out_of_service':
      return t('maintenance.events.out_of_service', { from: formatDate(String(d.start), language), until: formatDate(String(d.end), language) });
    case 'assigned':
      return d.to ? t('maintenance.events.assigned', { name: d.to }) : t('maintenance.events.unassigned');
    case 'edited':
      return t('maintenance.events.edited');
    case 'back_in_service':
      return t('maintenance.events.back_in_service');
    case 'comment':
      return t('maintenance.events.comment');
    default:
      return t('maintenance.events.reported');
  }
}

function CloseModal({ request: r, status, onClose, onDone }: { request: MaintenanceDetail; status: MaintenanceStatus; onClose: () => void; onDone: () => void }) {
  const { t } = useTranslation();
  const [text, setText] = useState('');
  const [release, setRelease] = useState(true);
  const [cleaning, setCleaning] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const save = useHotelMutation<Record<string, unknown>, MaintenanceDetail>((h, body) => api.post<MaintenanceDetail>(h(`/maintenance-requests/${r.id}/status`), body), ENTITIES);
  const completing = status === 'completed';
  return (
    <Modal opened onClose={onClose} title={t(`maintenance.actions.${status}`)}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          save
            .mutateAsync({
              version: r.version,
              status,
              resolution: completing ? text.trim() || undefined : undefined,
              comment: completing ? undefined : text.trim() || undefined,
              release_room: release,
              needs_cleaning: cleaning,
            })
            .then(() => {
              notifySuccess(t(completing ? 'maintenance.completed_done' : 'maintenance.cancelled_done'));
              onDone();
            }, (err) => setError(errorMessage(err)));
        }}
      >
        <Stack>
          {error && <Alert color="red">{error}</Alert>}
          <Textarea label={completing ? t('maintenance.resolution') : t('maintenance.cancel_reason')} autosize minRows={2} value={text} onChange={(e) => setText(e.currentTarget.value)} data-autofocus />
          {completing && r.block && <Checkbox label={t('maintenance.release_room')} checked={release} onChange={(e) => setRelease(e.currentTarget.checked)} />}
          {!completing && r.block && (
            <Text size="sm" c="dimmed">
              {t('maintenance.cancel_releases')}
            </Text>
          )}
          {completing && r.room_id && <Checkbox label={t('maintenance.needs_cleaning')} checked={cleaning} onChange={(e) => setCleaning(e.currentTarget.checked)} />}
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <SubmitButton color={completing ? 'teal' : 'red'} loading={save.isPending}>
              {t(`maintenance.actions.${status}`)}
            </SubmitButton>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

function BlockModal({ request: r, today, onClose }: { request: MaintenanceDetail; today: string; onClose: () => void }) {
  const { t } = useTranslation();
  const [dates, setDates] = useState<[string | null, string | null]>(r.block ? [r.block.start_date, r.block.end_date] : [today, addDays(today, 1)]);
  const [error, setError] = useState<string | null>(null);
  const save = useHotelMutation<Record<string, unknown>, MaintenanceDetail>((h, body) => api.post<MaintenanceDetail>(h(`/maintenance-requests/${r.id}/block`), body), ENTITIES);
  return (
    <Modal opened onClose={onClose} title={r.block ? t('maintenance.change_dates') : t('maintenance.take_out_of_service')}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!dates[0] || !dates[1]) return;
          save.mutateAsync({ version: r.version, start_date: dates[0], end_date: dates[1] }).then(() => {
            notifySuccess(t('maintenance.blocked_done'));
            onClose();
          }, (err) => setError(errorMessage(err)));
        }}
      >
        <Stack>
          {error && <Alert color="red">{error}</Alert>}
          <Text size="sm" c="dimmed">
            {t('maintenance.take_out_hint')}
          </Text>
          <DatePickerInput type="range" label={t('maintenance.out_of_service_dates')} value={dates} onChange={(v) => setDates([v[0], v[1]])} allowSingleDateInRange={false} valueFormat="ddd D MMM YYYY" />
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <SubmitButton color="red" loading={save.isPending} disabled={!dates[0] || !dates[1]}>
              {t('common.save')}
            </SubmitButton>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

