import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router';
import { Alert, Badge, Button, Card, Checkbox, Group, Loader, Modal, SegmentedControl, Select, SimpleGrid, Stack, Table, Tabs, Text, Textarea } from '@mantine/core';
import { IconCheck, IconListCheck, IconPlayerPlay, IconPlus, IconTool, IconX } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { api } from '@/api/client';
import { useHotelMutation, useHotelQuery } from '@/api/hooks';
import type { HousekeepingTask, Priority, StaffMember, TaskStatus, TaskType } from '@/api/types';
import { useAuth, useHotel } from '@/auth/AuthProvider';
import { EmptyState, PageHeader, SubmitButton } from '@/components/ui';
import { errorMessage, notifyError, notifySuccess } from '@/lib/errors';
import { formatDateTime } from '@/lib/format';
import { ReasonModal } from '@/modules/billing/FolioDialogs';
import { HousekeepingBadge, RoomBoard } from '@/modules/frontdesk/RoomBoard';
import { PRIORITIES, PriorityBadge, ReportIssueModal } from '@/modules/maintenance/shared';
import { useInventory } from '@/modules/reservations/shared';

const TASK_TYPES: TaskType[] = ['departure', 'stayover', 'deep_clean', 'touch_up', 'inspection'];
const STATUS_COLORS: Record<TaskStatus, string> = { pending: 'orange', in_progress: 'blue', done: 'teal', inspected: 'green', skipped: 'gray' };
const ENTITIES = ['housekeeping_task', 'room_board', 'room'];
type Tab = 'tasks' | 'mine' | 'rooms';

export function TaskStatusBadge({ status }: { status: TaskStatus }) {
  const { t } = useTranslation();
  return (
    <Badge color={STATUS_COLORS[status]} variant={status === 'in_progress' ? 'filled' : 'light'} radius="sm">
      {t(`housekeeping.statuses.${status}`)}
    </Badge>
  );
}

export default function HousekeepingPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const supervisor = can('housekeeping.assign');
  const [params, setParams] = useSearchParams();
  const fallback: Tab = supervisor ? 'tasks' : 'mine';
  const tab = (['tasks', 'mine', 'rooms'].includes(params.get('tab') ?? '') ? params.get('tab') : fallback) as Tab;
  const [adding, setAdding] = useState(false);
  const prepare = useHotelMutation<void, { created: number; existing: number }>((h) => api.post(h('/housekeeping/prepare')), ENTITIES);

  return (
    <>
      <PageHeader
        title={t('nav.housekeeping')}
        description={t('housekeeping.description')}
        actions={
          supervisor && (
            <>
              <Button
                variant="default"
                leftSection={<IconListCheck size={16} />}
                loading={prepare.isPending}
                onClick={() => prepare.mutateAsync().then((r) => notifySuccess(t('housekeeping.prepared', { count: r.created })), notifyError)}
              >
                {t('housekeeping.prepare')}
              </Button>
              <Button leftSection={<IconPlus size={16} />} onClick={() => setAdding(true)}>
                {t('housekeeping.add_task')}
              </Button>
            </>
          )
        }
      />
      <Tabs value={tab} onChange={(v) => v && setParams({ tab: v }, { replace: true })} keepMounted={false}>
        <Tabs.List mb="md">
          {supervisor && <Tabs.Tab value="tasks">{t('housekeeping.tabs.tasks')}</Tabs.Tab>}
          {can('housekeeping.update') && <Tabs.Tab value="mine">{t('housekeeping.tabs.mine')}</Tabs.Tab>}
          {!supervisor && !can('housekeeping.update') && <Tabs.Tab value="tasks">{t('housekeeping.tabs.tasks')}</Tabs.Tab>}
          <Tabs.Tab value="rooms">{t('housekeeping.tabs.rooms')}</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="tasks">
          <TaskTable />
        </Tabs.Panel>
        <Tabs.Panel value="mine">
          <MyTasks />
        </Tabs.Panel>
        <Tabs.Panel value="rooms">
          <RoomBoard />
        </Tabs.Panel>
      </Tabs>
      {adding && <AddTaskModal onClose={() => setAdding(false)} />}
    </>
  );
}

/** Start / done / skip for the assignee; inspect / reject / reopen for supervisors. */
function useTaskActions() {
  const { t } = useTranslation();
  const [asking, setAsking] = useState<{ task: HousekeepingTask; action: 'skip' | 'reject' } | null>(null);
  const act = useHotelMutation<{ id: string; action: string; reason?: string }, HousekeepingTask>(
    (h, { id, action, reason }) => api.post<HousekeepingTask>(h(`/housekeeping/tasks/${id}/${action}`), { reason }),
    ENTITIES,
  );
  const run = (task: HousekeepingTask, action: string, reason?: string) =>
    act.mutateAsync({ id: task.id, action, reason }).then(() => notifySuccess(t(`housekeeping.done_messages.${action}`, { room: task.room_number })));
  const element = asking && (
    <ReasonModal
      title={t(`housekeeping.actions.${asking.action}`)}
      body={t(`housekeeping.${asking.action}_body`, { room: asking.task.room_number })}
      confirm={t(`housekeeping.actions.${asking.action}`)}
      loading={act.isPending}
      onClose={() => setAsking(null)}
      onConfirm={(reason) => run(asking.task, asking.action, reason)}
    />
  );
  return { run: (task: HousekeepingTask, action: string) => run(task, action).catch(notifyError), ask: setAsking, busy: act.isPending, element };
}

function TaskButtons({ task, actions, size = 'xs' }: { task: HousekeepingTask; actions: ReturnType<typeof useTaskActions>; size?: 'xs' | 'md' }) {
  const { t } = useTranslation();
  const { can, me } = useAuth();
  const supervisor = can('housekeeping.assign');
  const mine = !task.assigned_to || task.assigned_to === me?.user.id || supervisor;
  const canWork = can('housekeeping.update') && mine;
  return (
    <Group gap={6} wrap="nowrap" justify="flex-end">
      {canWork && task.status === 'pending' && (
        <Button size={size} variant="light" leftSection={<IconPlayerPlay size={14} />} loading={actions.busy} onClick={() => void actions.run(task, 'start')}>
          {t('housekeeping.actions.start')}
        </Button>
      )}
      {canWork && (task.status === 'pending' || task.status === 'in_progress') && (
        <>
          <Button size={size} color="teal" leftSection={<IconCheck size={14} />} loading={actions.busy} onClick={() => void actions.run(task, 'complete')}>
            {t('housekeeping.actions.complete')}
          </Button>
          <Button size={size} variant="subtle" color="gray" onClick={() => actions.ask({ task, action: 'skip' })}>
            {t('housekeeping.actions.skip')}
          </Button>
        </>
      )}
      {supervisor && task.status === 'done' && (
        <>
          <Button size={size} color="green" variant="light" loading={actions.busy} onClick={() => void actions.run(task, 'inspect')}>
            {t('housekeeping.actions.inspect')}
          </Button>
          <Button size={size} variant="subtle" color="red" leftSection={<IconX size={14} />} onClick={() => actions.ask({ task, action: 'reject' })}>
            {t('housekeeping.actions.reject')}
          </Button>
        </>
      )}
      {supervisor && task.status === 'skipped' && (
        <Button size={size} variant="subtle" onClick={() => void actions.run(task, 'reopen')}>
          {t('housekeeping.actions.reopen')}
        </Button>
      )}
    </Group>
  );
}

function TaskTable() {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const { can } = useAuth();
  const supervisor = can('housekeeping.assign');
  const inv = useInventory();
  const [filter, setFilter] = useState<'open' | 'finished' | 'all'>('open');
  const [who, setWho] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const list = useHotelQuery<HousekeepingTask[]>('housekeeping_task', '/housekeeping/tasks');
  const staff = useHotelQuery<StaffMember[]>('housekeeping_task', '/housekeeping/staff');
  const actions = useTaskActions();
  const assign = useHotelMutation<{ ids: string[]; user: string | null }, unknown>(
    (h, { ids, user }) => api.post(h('/housekeeping/tasks/assign'), { task_ids: ids, user_id: user }),
    ENTITIES,
  );
  const rows = useMemo(
    () =>
      (list.data ?? []).filter(
        (x) =>
          (filter === 'all' || (filter === 'open' ? ['pending', 'in_progress', 'done'].includes(x.status) : ['inspected', 'skipped', 'done'].includes(x.status))) &&
          (!who || (who === 'none' ? !x.assigned_to : x.assigned_to === who)),
      ),
    [list.data, filter, who],
  );
  const staffOptions = (staff.data ?? []).map((u) => ({ value: u.id, label: u.full_name }));
  const counts = { pending: 0, in_progress: 0, done: 0 } as Record<string, number>;
  for (const x of list.data ?? []) counts[x.status] = (counts[x.status] ?? 0) + 1;
  if (list.isPending) return <Loader size="sm" />;

  return (
    <Stack>
      <Group gap="sm" wrap="wrap" justify="space-between">
        <Group gap="sm">
          <SegmentedControl
            value={filter}
            onChange={(v) => setFilter(v as typeof filter)}
            data={(['open', 'finished', 'all'] as const).map((f) => ({ value: f, label: t(`housekeeping.filters.${f}`) }))}
          />
          <Select placeholder={t('housekeeping.assigned_to')} clearable w={200} data={[{ value: 'none', label: t('housekeeping.unassigned') }, ...staffOptions]} value={who} onChange={setWho} />
        </Group>
        <Text size="sm" c="dimmed">
          {t('housekeeping.summary', { pending: counts.pending ?? 0, in_progress: counts.in_progress ?? 0, done: counts.done ?? 0 })}
        </Text>
      </Group>
      {supervisor && selected.size > 0 && (
        <Card padding="xs" withBorder>
          <Group gap="sm">
            <Text size="sm">{t('housekeeping.selected', { count: selected.size })}</Text>
            <Select
              placeholder={t('housekeeping.assign_to')}
              w={220}
              clearable
              data={[{ value: 'none', label: t('housekeeping.unassigned') }, ...staffOptions]}
              onChange={(v) =>
                v &&
                void assign.mutateAsync({ ids: [...selected], user: v === 'none' ? null : v }).then(() => {
                  notifySuccess(t('housekeeping.assigned_done', { count: selected.size }));
                  setSelected(new Set());
                }, notifyError)
              }
              value={null}
            />
          </Group>
        </Card>
      )}
      {rows.length === 0 ? (
        <EmptyState title={t('housekeeping.no_tasks')} description={supervisor ? t('housekeeping.no_tasks_hint') : undefined} />
      ) : (
        <Card padding={0}>
          <div className="hms-table-wrap">
            <Table verticalSpacing="sm" miw={760}>
              <Table.Thead>
                <Table.Tr>
                  {supervisor && (
                    <Table.Th w={36}>
                      <Checkbox
                        aria-label={t('housekeeping.select_all')}
                        checked={selected.size > 0 && rows.every((x) => selected.has(x.id))}
                        indeterminate={selected.size > 0 && !rows.every((x) => selected.has(x.id))}
                        onChange={(e) => setSelected(e.currentTarget.checked ? new Set(rows.map((x) => x.id)) : new Set())}
                      />
                    </Table.Th>
                  )}
                  <Table.Th>{t('rooms.number')}</Table.Th>
                  <Table.Th>{t('housekeeping.task')}</Table.Th>
                  <Table.Th>{t('housekeeping.assigned_to')}</Table.Th>
                  <Table.Th>{t('common.status')}</Table.Th>
                  <Table.Th />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {rows.map((x) => (
                  <Table.Tr key={x.id} data-task={`${x.room_number}-${x.task_type}`}>
                    {supervisor && (
                      <Table.Td>
                        <Checkbox
                          aria-label={x.room_number}
                          checked={selected.has(x.id)}
                          onChange={(e) => {
                            const next = new Set(selected);
                            if (e.currentTarget.checked) next.add(x.id);
                            else next.delete(x.id);
                            setSelected(next);
                          }}
                        />
                      </Table.Td>
                    )}
                    <Table.Td>
                      <Group gap={6} wrap="nowrap">
                        <Text fw={700} className="hms-num">
                          {x.room_number}
                        </Text>
                        <HousekeepingBadge status={x.room_status} />
                      </Group>
                      <Text size="xs" c="dimmed">
                        {inv.typeName(x.room_type_id)}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Group gap={6}>
                        <Text size="sm" fw={500}>
                          {t(`housekeeping.types.${x.task_type}`)}
                        </Text>
                        {x.priority !== 'normal' && <PriorityBadge priority={x.priority} size="xs" />}
                        {x.arrival_today && (
                          <Badge size="xs" color="brass" variant="light">
                            {t('housekeeping.arrival_today')}
                          </Badge>
                        )}
                      </Group>
                      {(x.notes || x.skip_reason) && (
                        <Text size="xs" c="dimmed" lineClamp={2}>
                          {x.skip_reason ? t('housekeeping.skipped_because', { reason: x.skip_reason === 'guest_departed' ? t('housekeeping.guest_departed') : x.skip_reason }) : x.notes}
                        </Text>
                      )}
                    </Table.Td>
                    <Table.Td>
                      {supervisor ? (
                        <Select
                          size="xs"
                          w={170}
                          clearable
                          placeholder={t('housekeeping.unassigned')}
                          data={staffOptions}
                          value={x.assigned_to}
                          aria-label={t('housekeeping.assigned_to')}
                          onChange={(v) => void assign.mutateAsync({ ids: [x.id], user: v }).catch(notifyError)}
                        />
                      ) : (
                        <Text size="sm">{x.assigned_to_name ?? '—'}</Text>
                      )}
                    </Table.Td>
                    <Table.Td>
                      <TaskStatusBadge status={x.status} />
                      {(x.completed_at || x.inspected_at) && (
                        <Text size="xs" c="dimmed">
                          {x.inspected_at
                            ? t('housekeeping.inspected_by', { name: x.inspected_by_name ?? '—', time: formatDateTime(x.inspected_at, i18n.language, hotel.timezone) })
                            : t('housekeeping.completed_by', { name: x.completed_by_name ?? '—', time: formatDateTime(x.completed_at, i18n.language, hotel.timezone) })}
                        </Text>
                      )}
                    </Table.Td>
                    <Table.Td>
                      <TaskButtons task={x} actions={actions} />
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </div>
        </Card>
      )}
      {actions.element}
    </Stack>
  );
}

/** Tablet-friendly list of the signed-in housekeeper's tasks. */
function MyTasks() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const inv = useInventory();
  const mine = useHotelQuery<HousekeepingTask[]>('housekeeping_task', '/housekeeping/tasks', { assigned_to: 'me' });
  const open = useHotelQuery<HousekeepingTask[]>('housekeeping_task', '/housekeeping/tasks', { unassigned: true, status: 'pending' });
  const actions = useTaskActions();
  const [reporting, setReporting] = useState<string | null>(null);
  if (mine.isPending) return <Loader size="sm" />;
  const todo = (mine.data ?? []).filter((x) => x.status === 'pending' || x.status === 'in_progress');
  const finished = (mine.data ?? []).filter((x) => !(x.status === 'pending' || x.status === 'in_progress'));
  const card = (x: HousekeepingTask) => (
    <Card key={x.id} withBorder padding="md" data-my-task={x.room_number} style={{ borderLeft: `4px solid var(--mantine-color-${STATUS_COLORS[x.status]}-6)` }}>
      <Group justify="space-between" align="flex-start" wrap="nowrap">
        <div>
          <Group gap={8}>
            <Text fw={800} size="xl" className="hms-num">
              {x.room_number}
            </Text>
            <HousekeepingBadge status={x.room_status} />
            {x.priority !== 'normal' && <PriorityBadge priority={x.priority} size="sm" />}
          </Group>
          <Text size="sm" fw={500}>
            {t(`housekeeping.types.${x.task_type}`)} · {inv.typeName(x.room_type_id)}
          </Text>
          {x.arrival_today && (
            <Text size="sm" c="brass.8" fw={600}>
              {t('housekeeping.arrival_today_hint')}
            </Text>
          )}
          {x.notes && (
            <Text size="sm" c="dimmed">
              {x.notes}
            </Text>
          )}
        </div>
        <TaskStatusBadge status={x.status} />
      </Group>
      <Group mt="sm" justify="space-between" wrap="wrap">
        {can('maintenance.report') ? (
          <Button size="md" variant="subtle" color="orange" leftSection={<IconTool size={16} />} onClick={() => setReporting(x.room_id)}>
            {t('housekeeping.report_issue')}
          </Button>
        ) : (
          <span />
        )}
        <TaskButtons task={x} actions={actions} size="md" />
      </Group>
    </Card>
  );
  return (
    <Stack>
      {todo.length === 0 && (open.data ?? []).length === 0 && <EmptyState title={t('housekeeping.nothing_to_do')} />}
      <SimpleGrid cols={{ base: 1, md: 2 }}>{todo.map(card)}</SimpleGrid>
      {(open.data ?? []).length > 0 && (
        <>
          <Text fw={600} mt="md">
            {t('housekeeping.unassigned_tasks')}
          </Text>
          <SimpleGrid cols={{ base: 1, md: 2 }}>{(open.data ?? []).map(card)}</SimpleGrid>
        </>
      )}
      {finished.length > 0 && (
        <>
          <Text fw={600} mt="md" c="dimmed">
            {t('housekeeping.finished_today', { count: finished.length })}
          </Text>
          <SimpleGrid cols={{ base: 1, md: 2 }}>{finished.map(card)}</SimpleGrid>
        </>
      )}
      {actions.element}
      {reporting && <ReportIssueModal roomId={reporting} onClose={() => setReporting(null)} />}
    </Stack>
  );
}

function AddTaskModal({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const inv = useInventory();
  const staff = useHotelQuery<StaffMember[]>('housekeeping_task', '/housekeeping/staff');
  const [room, setRoom] = useState<string | null>(null);
  const [type, setType] = useState<TaskType>('touch_up');
  const [priority, setPriority] = useState<Priority>('normal');
  const [assignee, setAssignee] = useState<string | null>(null);
  const [notes, setNotes] = useState('');
  const [error, setError] = useState<string | null>(null);
  const create = useHotelMutation<Record<string, unknown>, HousekeepingTask>((h, body) => api.post<HousekeepingTask>(h('/housekeeping/tasks'), body), ENTITIES);
  return (
    <Modal opened onClose={onClose} title={t('housekeeping.add_task')}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!room) return;
          create.mutateAsync({ room_id: room, task_type: type, priority, assigned_to: assignee, notes: notes.trim() || undefined }).then(() => {
            notifySuccess(t('housekeeping.task_added'));
            onClose();
          }, (err) => setError(errorMessage(err)));
        }}
      >
        <Stack>
          {error && <Alert color="red">{error}</Alert>}
          <Select label={t('rooms.number')} searchable required data={inv.rooms.filter((r) => r.is_active).map((r) => ({ value: r.id, label: `${r.number} · ${inv.typeName(r.room_type_id)}` }))} value={room} onChange={setRoom} />
          <SimpleGrid cols={2}>
            <Select label={t('housekeeping.task')} allowDeselect={false} data={TASK_TYPES.map((x) => ({ value: x, label: t(`housekeeping.types.${x}`) }))} value={type} onChange={(v) => v && setType(v as TaskType)} />
            <Select label={t('maintenance.priority')} allowDeselect={false} data={PRIORITIES.map((p) => ({ value: p, label: t(`maintenance.priorities.${p}`) }))} value={priority} onChange={(v) => v && setPriority(v as Priority)} />
          </SimpleGrid>
          <Select label={t('housekeeping.assigned_to')} clearable data={(staff.data ?? []).map((u) => ({ value: u.id, label: u.full_name }))} value={assignee} onChange={setAssignee} />
          <Textarea label={t('housekeeping.notes')} autosize minRows={2} maxLength={2000} value={notes} onChange={(e) => setNotes(e.currentTarget.value)} />
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <SubmitButton loading={create.isPending} disabled={!room}>
              {t('housekeeping.add_task')}
            </SubmitButton>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}
