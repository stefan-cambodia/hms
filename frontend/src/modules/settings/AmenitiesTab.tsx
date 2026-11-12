import { useState } from 'react';
import { ActionIcon, Button, Group, Modal, NumberInput, SegmentedControl, Stack, Switch, Table, Text, TextInput } from '@mantine/core';
import { useForm } from '@mantine/form';
import { IconEdit, IconPlus, IconTrash } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { useCrud, useHotelQuery } from '@/api/hooks';
import type { Amenity, Hotel } from '@/api/types';
import { useAuth, useHotel } from '@/auth/AuthProvider';
import { LocalizedTextInput } from '@/components/LocalizedTextInput';
import { ActiveBadge, confirmDelete, SubmitButton } from '@/components/ui';
import { LANGUAGES } from '@/i18n';
import { applyFieldErrors, notifyError, notifySuccess } from '@/lib/errors';
import { hasTranslation, type LocalizedText, pickLocalized } from '@/lib/localized';

interface Draft {
  id?: string;
  version?: number;
  code: string;
  name: LocalizedText;
  icon: string;
  scope: 'room' | 'hotel';
  sort_order: number;
  is_active: boolean;
}

export default function AmenitiesTab() {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const { can } = useAuth();
  const canEdit = can('config.rooms.manage');
  const list = useHotelQuery<Amenity[]>('amenity', '/amenities');
  const profile = useHotelQuery<Hotel>('hotel', '');
  const crud = useCrud<Amenity>('amenity', '/amenities', ['amenity', 'room_type', 'room']);
  const [draft, setDraft] = useState<Draft | null>(null);
  const languages = profile.data?.supported_languages ?? [hotel.default_language];

  return (
    <Stack>
      <Group justify="space-between">
        <Text c="dimmed" size="sm" maw={640}>
          {t('settings.amenities.hint')}
        </Text>
        {canEdit && (
          <Button leftSection={<IconPlus size={16} />} onClick={() => setDraft({ code: '', name: {}, icon: '', scope: 'room', sort_order: 0, is_active: true })}>
            {t('settings.amenities.add')}
          </Button>
        )}
      </Group>
      <div className="hms-table-wrap">
        <Table miw={600}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t('common.name')}</Table.Th>
              <Table.Th>{t('settings.amenities.scope')}</Table.Th>
              <Table.Th>{t('settings.amenities.translations')}</Table.Th>
              <Table.Th>{t('common.status')}</Table.Th>
              {canEdit && <Table.Th w={80} />}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {list.data?.map((a) => (
              <Table.Tr key={a.id}>
                <Table.Td>
                  <Text size="sm" fw={600}>
                    {pickLocalized(a.name, i18n.language, hotel.default_language)}
                  </Text>
                  <Text size="xs" c="dimmed">
                    {a.code}
                  </Text>
                </Table.Td>
                <Table.Td>{t(`settings.amenities.scope_${a.scope}`)}</Table.Td>
                <Table.Td>
                  <Text size="xs" c="dimmed">
                    {LANGUAGES.filter((l) => hasTranslation(a.name, l.code))
                      .map((l) => l.code)
                      .join(' · ')}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <ActiveBadge active={a.is_active} />
                </Table.Td>
                {canEdit && (
                  <Table.Td>
                    <Group gap={4} justify="flex-end" wrap="nowrap">
                      <ActionIcon variant="subtle" aria-label={t('common.edit')} onClick={() => setDraft({ ...a, icon: a.icon ?? '' })}>
                        <IconEdit size={16} />
                      </ActionIcon>
                      <ActionIcon
                        variant="subtle"
                        color="red"
                        aria-label={t('common.delete')}
                        onClick={() =>
                          confirmDelete({
                            title: t('settings.amenities.delete', { name: pickLocalized(a.name, i18n.language) }),
                            onConfirm: () => crud.remove.mutateAsync(a.id).then(() => notifySuccess(t('common.deleted')), notifyError),
                          })
                        }
                      >
                        <IconTrash size={16} />
                      </ActionIcon>
                    </Group>
                  </Table.Td>
                )}
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </div>
      {draft && <AmenityModal draft={draft} languages={languages} crud={crud} onClose={() => setDraft(null)} />}
    </Stack>
  );
}

function AmenityModal({ draft, languages, crud, onClose }: { draft: Draft; languages: string[]; crud: ReturnType<typeof useCrud<Amenity>>; onClose: () => void }) {
  const { t } = useTranslation();
  const form = useForm<Draft>({ initialValues: draft });
  const submit = form.onSubmit(async ({ id, version, ...values }) => {
    const body = { ...values, icon: values.icon || null };
    try {
      if (id) await crud.update.mutateAsync({ id, body: { ...body, version } });
      else await crud.create.mutateAsync(body as never);
      notifySuccess(t('common.saved'));
      onClose();
    } catch (err) {
      if (!applyFieldErrors(err, form.setFieldError)) notifyError(err);
    }
  });
  return (
    <Modal opened onClose={onClose} title={draft.id ? t('settings.amenities.edit') : t('settings.amenities.add')} size="lg">
      <form onSubmit={submit}>
        <Stack>
          <TextInput label={t('common.code')} description={t('common.code_hint')} required {...form.getInputProps('code')} />
          <LocalizedTextInput label={t('common.name')} required languages={languages} value={form.getValues().name} onChange={(x) => form.setFieldValue('name', x)} error={form.errors.name as string} />
          <SegmentedControl
            data={[
              { value: 'room', label: t('settings.amenities.scope_room') },
              { value: 'hotel', label: t('settings.amenities.scope_hotel') },
            ]}
            {...form.getInputProps('scope')}
          />
          <Group grow>
            <NumberInput label={t('common.sort_order')} min={0} {...form.getInputProps('sort_order')} />
            <Switch mt={24} label={t('common.active')} {...form.getInputProps('is_active', { type: 'checkbox' })} />
          </Group>
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <SubmitButton loading={crud.create.isPending || crud.update.isPending}>{t('common.save')}</SubmitButton>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}
