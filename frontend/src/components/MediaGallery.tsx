import { useState } from 'react';
import { ActionIcon, AspectRatio, Box, Button, FileButton, Group, Image, Modal, SimpleGrid, Stack, Text, Tooltip, UnstyledButton } from '@mantine/core';
import { useQueryClient } from '@tanstack/react-query';
import { IconChevronLeft, IconChevronRight, IconPhotoPlus, IconTrash } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { api, ApiError } from '@/api/client';
import { useHotelQuery } from '@/api/hooks';
import { hotelKey, useConnectionStatus } from '@/api/realtime';
import type { MediaFile, MediaOwnerType } from '@/api/types';
import { useHotel } from '@/auth/AuthProvider';
import { confirmDelete } from '@/components/ui';
import { notifyError, notifySuccess } from '@/lib/errors';
import { formatDateTime } from '@/lib/format';

/** What the server accepts (it checks the bytes, not this list). Listing the
 * types makes iPads convert HEIC camera photos to JPEG when uploading. */
export const IMAGE_ACCEPT = 'image/jpeg,image/png,image/webp';

/** Photos (or the logo) of one owner, in display order. */
export function useMedia(ownerType: MediaOwnerType, ownerId?: string | null, enabled = true) {
  return useHotelQuery<MediaFile[]>('media', '/media', { owner_type: ownerType, owner_id: ownerId ?? undefined }, enabled && (ownerType === 'hotel' || !!ownerId));
}

/** Upload files one after the other. Returns how many were refused (each refusal is shown). */
export async function uploadImages(hotelId: string, ownerType: MediaOwnerType, ownerId: string | null, files: File[], onProgress?: (done: number) => void): Promise<number> {
  let failed = 0;
  for (const [i, file] of files.entries()) {
    const form = new FormData();
    form.append('owner_type', ownerType);
    if (ownerId) form.append('owner_id', ownerId);
    form.append('file', file, file.name);
    try {
      await api.upload<MediaFile>(`/hotels/${hotelId}/media`, form);
    } catch (err) {
      failed += 1;
      notifyError(err);
    }
    onProgress?.(i + 1);
  }
  return failed;
}

export function useInvalidateMedia() {
  const hotel = useHotel();
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: hotelKey(hotel.id, 'media') });
}

interface GalleryProps {
  ownerType: Exclude<MediaOwnerType, 'hotel'>;
  ownerId: string;
  canEdit: boolean;
  /** Who may remove a given photo (default: whoever can edit). */
  canDelete?: (m: MediaFile) => boolean;
  limit: number;
}

export function MediaGallery({ ownerType, ownerId, canEdit, canDelete, limit }: GalleryProps) {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const offline = useConnectionStatus() === 'offline';
  const media = useMedia(ownerType, ownerId);
  const invalidate = useInvalidateMedia();
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const [viewing, setViewing] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const items = media.data ?? [];
  const room = limit - items.length;
  const mayDelete = (m: MediaFile) => (canDelete ? canDelete(m) : canEdit);

  const add = async (files: File[]) => {
    if (!files.length) return;
    const batch = files.slice(0, Math.max(room, 0));
    if (batch.length < files.length) notifyError(new ApiError(409, 'MEDIA_LIMIT_REACHED', '', { limit }));
    if (!batch.length) return;
    setProgress({ done: 0, total: batch.length });
    const failed = await uploadImages(hotel.id, ownerType, ownerId, batch, (done) => setProgress({ done, total: batch.length }));
    setProgress(null);
    await invalidate();
    if (failed < batch.length) notifySuccess(t('media.added'));
  };

  const move = async (index: number, delta: number) => {
    const ids = items.map((m) => m.id);
    const [moved] = ids.splice(index, 1);
    ids.splice(index + delta, 0, moved);
    setBusy(true);
    try {
      await api.put(`/hotels/${hotel.id}/media/order`, { owner_type: ownerType, owner_id: ownerId, ids });
      await invalidate();
    } catch (err) {
      notifyError(err);
    } finally {
      setBusy(false);
    }
  };

  const remove = (m: MediaFile) =>
    confirmDelete({
      title: t('media.delete_title'),
      message: m.filename,
      onConfirm: async () => {
        try {
          await api.delete(`/hotels/${hotel.id}/media/${m.id}`);
          setViewing(null);
          await invalidate();
          notifySuccess(t('common.deleted'));
        } catch (err) {
          notifyError(err);
        }
      },
    });

  const current = viewing !== null ? items[viewing] : undefined;

  return (
    <Stack gap="xs" data-testid={`media-${ownerType}`}>
      <Group justify="space-between" wrap="nowrap">
        <Text size="sm" fw={600}>
          {t('media.photos')}{' '}
          <Text span size="xs" c="dimmed" fw={400}>
            {t('media.count', { n: items.length, limit })}
          </Text>
        </Text>
        {canEdit && (
          <FileButton onChange={(files) => void add(files)} accept={IMAGE_ACCEPT} multiple>
            {(props) => (
              <Button {...props} size="xs" variant="light" leftSection={<IconPhotoPlus size={16} />} loading={!!progress} disabled={offline || room <= 0}>
                {t('media.add_photos')}
              </Button>
            )}
          </FileButton>
        )}
      </Group>
      {progress && (
        <Text size="xs" c="dimmed">
          {t('media.uploading', { done: progress.done, total: progress.total })}
        </Text>
      )}
      {items.length === 0 ? (
        <Text size="sm" c="dimmed">
          {t('media.empty')}
        </Text>
      ) : (
        <SimpleGrid cols={{ base: 3, sm: 4 }} spacing="xs">
          {items.map((m, i) => (
            <Box key={m.id} pos="relative" data-media-id={m.id}>
              <UnstyledButton onClick={() => setViewing(i)} aria-label={t('media.view', { name: m.filename })} w="100%" style={{ display: 'block', borderRadius: 6, overflow: 'hidden' }}>
                <AspectRatio ratio={4 / 3}>
                  <Image src={m.thumbnail_url} alt={m.filename} fit="cover" loading="lazy" bg="gray.1" />
                </AspectRatio>
              </UnstyledButton>
              {(canEdit || mayDelete(m)) && (
                <Group gap={2} pos="absolute" bottom={4} right={4} className="hms-media-actions">
                  {canEdit && i > 0 && (
                    <Tooltip label={t('media.move_earlier')}>
                      <ActionIcon size="sm" variant="white" color="dark" aria-label={t('media.move_earlier')} disabled={busy || offline} onClick={() => void move(i, -1)}>
                        <IconChevronLeft size={14} />
                      </ActionIcon>
                    </Tooltip>
                  )}
                  {canEdit && i < items.length - 1 && (
                    <Tooltip label={t('media.move_later')}>
                      <ActionIcon size="sm" variant="white" color="dark" aria-label={t('media.move_later')} disabled={busy || offline} onClick={() => void move(i, 1)}>
                        <IconChevronRight size={14} />
                      </ActionIcon>
                    </Tooltip>
                  )}
                  {mayDelete(m) && (
                    <ActionIcon size="sm" variant="white" color="red" aria-label={t('common.delete')} disabled={offline} onClick={() => remove(m)}>
                      <IconTrash size={14} />
                    </ActionIcon>
                  )}
                </Group>
              )}
            </Box>
          ))}
        </SimpleGrid>
      )}
      <Text size="xs" c="dimmed">
        {t('media.formats_hint')}
      </Text>

      <Modal opened={!!current} onClose={() => setViewing(null)} size="xl" title={current?.filename} centered>
        {current && viewing !== null && (
          <Stack gap="xs">
            <Image src={current.url} alt={current.filename} fit="contain" mah="70vh" radius="sm" />
            <Group justify="space-between" wrap="nowrap">
              <Text size="xs" c="dimmed">
                {[current.uploaded_by_name, formatDateTime(current.created_at, i18n.language, hotel.timezone)].filter(Boolean).join(' · ')}
              </Text>
              <Group gap="xs" wrap="nowrap">
                <ActionIcon variant="default" aria-label={t('media.previous')} disabled={viewing === 0} onClick={() => setViewing(viewing - 1)}>
                  <IconChevronLeft size={16} />
                </ActionIcon>
                <Text size="xs" c="dimmed">
                  {viewing + 1} / {items.length}
                </Text>
                <ActionIcon variant="default" aria-label={t('media.next')} disabled={viewing === items.length - 1} onClick={() => setViewing(viewing + 1)}>
                  <IconChevronRight size={16} />
                </ActionIcon>
                {mayDelete(current) && (
                  <Button size="xs" variant="light" color="red" leftSection={<IconTrash size={14} />} disabled={offline} onClick={() => remove(current)}>
                    {t('common.delete')}
                  </Button>
                )}
              </Group>
            </Group>
          </Stack>
        )}
      </Modal>
    </Stack>
  );
}
