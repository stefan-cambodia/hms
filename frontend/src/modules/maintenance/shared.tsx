import { useState } from 'react';
import { Alert, Badge, type BadgeProps, Button, Checkbox, Group, Modal, SegmentedControl, Select, SimpleGrid, Stack, Textarea, TextInput } from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import { useTranslation } from 'react-i18next';

import { api } from '@/api/client';
import { useHotelMutation } from '@/api/hooks';
import type { MaintenanceCategory, MaintenanceDetail, MaintenanceStatus, Priority } from '@/api/types';
import { useAuth } from '@/auth/AuthProvider';
import { SubmitButton } from '@/components/ui';
import { addDays } from '@/lib/dates';
import { errorMessage, notifySuccess } from '@/lib/errors';
import { useHotelToday, useInventory } from '@/modules/reservations/shared';

export const CATEGORIES: MaintenanceCategory[] = ['plumbing', 'electrical', 'air_conditioning', 'furniture', 'appliance', 'building', 'it_network', 'pest_control', 'other'];
export const PRIORITIES: Priority[] = ['low', 'normal', 'high', 'urgent'];
export const PRIORITY_COLORS: Record<Priority, string> = { low: 'gray', normal: 'blue', high: 'orange', urgent: 'red' };
const STATUS_COLORS: Record<MaintenanceStatus, string> = { reported: 'orange', in_progress: 'blue', on_hold: 'gray', completed: 'teal', cancelled: 'gray' };

export function PriorityBadge({ priority, ...props }: { priority: Priority } & BadgeProps) {
  const { t } = useTranslation();
  return (
    <Badge color={PRIORITY_COLORS[priority]} variant={priority === 'urgent' ? 'filled' : 'light'} radius="sm" {...props}>
      {t(`maintenance.priorities.${priority}`)}
    </Badge>
  );
}

export function MaintenanceStatusBadge({ status, ...props }: { status: MaintenanceStatus } & BadgeProps) {
  const { t } = useTranslation();
  return (
    <Badge color={STATUS_COLORS[status]} variant="light" radius="sm" {...props}>
      {t(`maintenance.statuses.${status}`)}
    </Badge>
  );
}

/** Report a problem on a room or anywhere in the hotel (maintenance.report). */
export function ReportIssueModal({ roomId, onClose, onCreated }: { roomId?: string; onClose: () => void; onCreated?: (r: MaintenanceDetail) => void }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const inv = useInventory();
  const today = useHotelToday();
  const [where, setWhere] = useState<'room' | 'location'>('room');
  const [room, setRoom] = useState<string | null>(roomId ?? null);
  const [location, setLocation] = useState('');
  const [category, setCategory] = useState<MaintenanceCategory>('other');
  const [priority, setPriority] = useState<Priority>('normal');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [block, setBlock] = useState(false);
  const [dates, setDates] = useState<[string | null, string | null]>([today, addDays(today, 1)]);
  const [error, setError] = useState<string | null>(null);
  const create = useHotelMutation<Record<string, unknown>, MaintenanceDetail>((h, body) => api.post<MaintenanceDetail>(h('/maintenance-requests'), body), [
    'maintenance_request',
    'room_board',
    'calendar',
  ]);
  const valid = title.trim() && (where === 'room' ? !!room : !!location.trim()) && (!block || (dates[0] && dates[1]));
  const submit = () => {
    setError(null);
    create
      .mutateAsync({
        room_id: where === 'room' ? room : undefined,
        location: where === 'location' ? location.trim() : undefined,
        category,
        priority,
        title: title.trim(),
        description: description.trim() || undefined,
        out_of_service: where === 'room' && block ? { start_date: dates[0], end_date: dates[1] } : undefined,
      })
      .then(
        (r) => {
          notifySuccess(t('maintenance.reported_done', { number: r.number }));
          onCreated?.(r);
          onClose();
        },
        (err) => setError(errorMessage(err)),
      );
  };
  return (
    <Modal opened onClose={onClose} title={t('maintenance.report')} size="lg">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (valid) submit();
        }}
      >
        <Stack>
          {error && <Alert color="red">{error}</Alert>}
          <SegmentedControl
            value={where}
            onChange={(v) => setWhere(v as 'room' | 'location')}
            data={[
              { value: 'room', label: t('maintenance.in_room') },
              { value: 'location', label: t('maintenance.elsewhere') },
            ]}
          />
          {where === 'room' ? (
            <Select
              label={t('rooms.number')}
              searchable
              required
              data={inv.rooms.filter((r) => r.is_active).map((r) => ({ value: r.id, label: `${r.number} · ${inv.typeName(r.room_type_id)}` }))}
              value={room}
              onChange={setRoom}
            />
          ) : (
            <TextInput label={t('maintenance.location')} placeholder={t('maintenance.location_placeholder')} required maxLength={200} value={location} onChange={(e) => setLocation(e.currentTarget.value)} />
          )}
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <Select
              label={t('maintenance.category')}
              allowDeselect={false}
              data={CATEGORIES.map((c) => ({ value: c, label: t(`maintenance.categories.${c}`) }))}
              value={category}
              onChange={(v) => v && setCategory(v as MaintenanceCategory)}
            />
            <Select
              label={t('maintenance.priority')}
              allowDeselect={false}
              data={PRIORITIES.map((p) => ({ value: p, label: t(`maintenance.priorities.${p}`) }))}
              value={priority}
              onChange={(v) => v && setPriority(v as Priority)}
            />
          </SimpleGrid>
          <TextInput label={t('maintenance.title')} placeholder={t('maintenance.title_placeholder')} required maxLength={200} value={title} onChange={(e) => setTitle(e.currentTarget.value)} data-autofocus />
          <Textarea label={t('maintenance.details')} autosize minRows={2} maxLength={5000} value={description} onChange={(e) => setDescription(e.currentTarget.value)} />
          {where === 'room' && can('maintenance.manage') && (
            <>
              <Checkbox label={t('maintenance.take_out_of_service')} description={t('maintenance.take_out_hint')} checked={block} onChange={(e) => setBlock(e.currentTarget.checked)} />
              {block && (
                <DatePickerInput
                  type="range"
                  label={t('maintenance.out_of_service_dates')}
                  value={dates}
                  onChange={(v) => setDates([v[0], v[1]])}
                  allowSingleDateInRange={false}
                  valueFormat="ddd D MMM YYYY"
                />
              )}
            </>
          )}
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <SubmitButton loading={create.isPending} disabled={!valid}>
              {t('maintenance.send_report')}
            </SubmitButton>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

export function useWhere() {
  const { t } = useTranslation();
  return (r: { room_number: string | null; location: string | null }) => (r.room_number ? t('maintenance.room_label', { number: r.room_number }) : (r.location ?? '—'));
}
