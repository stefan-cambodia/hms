import { type ReactNode, useState } from 'react';
import { Button, Card, Center, FileButton, Group, Image, Stack, Text } from '@mantine/core';
import { modals } from '@mantine/modals';
import { IconPhotoUp, IconTrash } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { api } from '@/api/client';
import { useConnectionStatus } from '@/api/realtime';
import { useHotel } from '@/auth/AuthProvider';
import { IMAGE_ACCEPT, uploadImages, useInvalidateMedia, useMedia } from '@/components/MediaGallery';
import { SectionTitle } from '@/components/ui';
import { notifyError, notifySuccess } from '@/lib/errors';

/** The hotel's logo next to its name in the header, or `fallback` while there is none. */
export function HeaderLogo({ fallback }: { fallback: ReactNode }) {
  const logo = useMedia('hotel').data?.[0];
  if (!logo) return <>{fallback}</>;
  return <Image src={logo.thumbnail_url} alt="" h={28} w="auto" maw={96} fit="contain" data-testid="header-logo" />;
}

/** Hotel profile: upload, replace or remove the logo (saved at once, not with the form). */
export function LogoCard({ canEdit }: { canEdit: boolean }) {
  const { t } = useTranslation();
  const hotel = useHotel();
  const offline = useConnectionStatus() === 'offline';
  const logo = useMedia('hotel').data?.[0];
  const invalidate = useInvalidateMedia();
  const [busy, setBusy] = useState(false);

  const upload = async (file: File | null) => {
    if (!file) return;
    setBusy(true);
    const failed = await uploadImages(hotel.id, 'hotel', null, [file]);
    await invalidate();
    setBusy(false);
    if (!failed) notifySuccess(t('media.logo.saved'));
  };

  const remove = () =>
    modals.openConfirmModal({
      title: t('media.logo.remove'),
      children: <Text size="sm">{t('media.logo.remove_confirm')}</Text>,
      labels: { confirm: t('media.logo.remove'), cancel: t('common.cancel') },
      confirmProps: { color: 'red' },
      onConfirm: async () => {
        if (!logo) return;
        try {
          await api.delete(`/hotels/${hotel.id}/media/${logo.id}`);
          await invalidate();
          notifySuccess(t('media.logo.removed'));
        } catch (err) {
          notifyError(err);
        }
      },
    });

  return (
    <Card data-testid="logo-card">
      <SectionTitle description={t('media.logo.hint')}>{t('media.logo.title')}</SectionTitle>
      <Group align="center" gap="lg" wrap="wrap">
        <Center w={220} h={96} bg="gray.0" style={{ border: '1px dashed var(--mantine-color-gray-4)', borderRadius: 8 }}>
          {logo ? (
            <Image src={logo.thumbnail_url} alt={t('media.logo.title')} mah={80} maw={200} fit="contain" />
          ) : (
            <Text size="sm" c="dimmed">
              {t('media.logo.none')}
            </Text>
          )}
        </Center>
        {canEdit && (
          <Stack gap="xs">
            <FileButton onChange={(f) => void upload(f)} accept={IMAGE_ACCEPT}>
              {(props) => (
                <Button {...props} variant="light" leftSection={<IconPhotoUp size={16} />} loading={busy} disabled={offline}>
                  {logo ? t('media.logo.replace') : t('media.logo.upload')}
                </Button>
              )}
            </FileButton>
            {logo && (
              <Button variant="subtle" color="red" leftSection={<IconTrash size={16} />} disabled={offline} onClick={remove}>
                {t('media.logo.remove')}
              </Button>
            )}
          </Stack>
        )}
      </Group>
      <Text size="xs" c="dimmed" mt="sm">
        {t('media.formats_hint')}
      </Text>
    </Card>
  );
}
