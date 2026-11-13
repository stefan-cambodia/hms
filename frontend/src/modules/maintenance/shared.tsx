import { useEffect, useMemo, useState } from 'react';
import { ActionIcon, Alert, Badge, type BadgeProps, Box, Button, Checkbox, FileButton, Group, Image, Modal, SegmentedControl, Select, SimpleGrid, Stack, Text, Textarea, TextInput } from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import { IconCamera, IconX } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { api } from '@/api/client';
import { useHotelMutation } from '@/api/hooks';
import type { MaintenanceCategory, MaintenanceDetail, MaintenanceStatus, Priority } from '@/api/types';
import { useAuth, useHotel } from '@/auth/AuthProvider';
import { IMAGE_ACCEPT, uploadImages, useInvalidateMedia } from '@/components/MediaGallery';
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
const MAX_PHOTOS = 10;

/** A chosen photo before it is sent, with a button to drop it. */
function PhotoPreview({ file, onRemove }: { file: File; onRemove: () => void }) {
  const { t } = useTranslation();
  const url = useMemo(() => URL.createObjectURL(file), [file]);
  useEffect(() => () => URL.revokeObjectURL(url), [url]);
  return (
    <Box pos="relative" data-testid="photo-preview">
      <Image src={url} alt={file.name} w={48} h={48} radius="sm" fit="cover" />
      <ActionIcon size={18} radius="xl" color="dark" pos="absolute" top={-6} right={-6} aria-label={t('common.remove')} onClick={onRemove}>
        <IconX size={12} />
      </ActionIcon>
    </Box>
  );
}

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
  const hotel = useHotel();
  const [photos, setPhotos] = useState<File[]>([]);
  const [sendingPhotos, setSendingPhotos] = useState(false);
  const invalidateMedia = useInvalidateMedia();
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
        async (r) => {
          // The report is saved first; a refused photo never loses it.
          if (photos.length) {
            setSendingPhotos(true);
            await uploadImages(hotel.id, 'maintenance_request', r.id, photos);
            setSendingPhotos(false);
            void invalidateMedia();
          }
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
          <Stack gap={6}>
            <Group gap="xs" wrap="wrap">
              <FileButton onChange={(files) => setPhotos((p) => [...p, ...files].slice(0, MAX_PHOTOS))} accept={IMAGE_ACCEPT} multiple>
                {(props) => (
                  <Button {...props} variant="default" size="xs" leftSection={<IconCamera size={16} />} disabled={photos.length >= MAX_PHOTOS}>
                    {t('maintenance.attach_photos')}
                  </Button>
                )}
              </FileButton>
              {photos.map((file, i) => (
                <PhotoPreview key={`${file.name}-${file.size}-${i}`} file={file} onRemove={() => setPhotos((p) => p.filter((_, j) => j !== i))} />
              ))}
            </Group>
            <Text size="xs" c="dimmed">
              {t('media.formats_hint')}
            </Text>
          </Stack>
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
            <SubmitButton loading={create.isPending || sendingPhotos} disabled={!valid}>
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
