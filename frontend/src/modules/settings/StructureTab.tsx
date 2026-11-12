import { useState } from 'react';
import { ActionIcon, Badge, Button, Card, Group, Modal, NumberInput, SimpleGrid, Stack, Switch, Table, Text, TextInput } from '@mantine/core';
import { useForm } from '@mantine/form';
import { IconEdit, IconPlus, IconTrash } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { useCrud, useHotelQuery } from '@/api/hooks';
import type { Building, Floor, Room } from '@/api/types';
import { useAuth } from '@/auth/AuthProvider';
import { ActiveBadge, confirmDelete, EmptyState, SubmitButton } from '@/components/ui';
import { applyFieldErrors, notifyError, notifySuccess } from '@/lib/errors';

type BuildingDraft = { id?: string; version?: number; code: string; name: string; sort_order: number; is_active: boolean };
type FloorDraft = { id?: string; version?: number; building_id: string; level: number; name: string; sort_order: number };

export default function StructureTab() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const canEdit = can('config.rooms.manage');
  const buildings = useHotelQuery<Building[]>('building', '/buildings');
  const floors = useHotelQuery<Floor[]>('floor', '/floors');
  const rooms = useHotelQuery<Room[]>('room', '/rooms');
  const buildingCrud = useCrud<Building>('building', '/buildings', ['building', 'floor', 'room']);
  const floorCrud = useCrud<Floor>('floor', '/floors', ['floor', 'room']);
  const [buildingDraft, setBuildingDraft] = useState<BuildingDraft | null>(null);
  const [floorDraft, setFloorDraft] = useState<FloorDraft | null>(null);

  const roomsOnFloor = (floorId: string) => rooms.data?.filter((r) => r.floor_id === floorId && r.is_active).length ?? 0;

  return (
    <Stack>
      <Group justify="space-between">
        <Text c="dimmed" size="sm" maw={640}>
          {t('settings.structure.hint')}
        </Text>
        {canEdit && (
          <Button leftSection={<IconPlus size={16} />} onClick={() => setBuildingDraft({ code: '', name: '', sort_order: 0, is_active: true })}>
            {t('settings.structure.add_building')}
          </Button>
        )}
      </Group>

      {buildings.data?.length === 0 && <EmptyState title={t('settings.structure.empty')} description={t('settings.structure.empty_hint')} />}

      <SimpleGrid cols={{ base: 1, lg: 2 }}>
        {buildings.data?.map((b) => {
          const bFloors = (floors.data ?? []).filter((f) => f.building_id === b.id).sort((x, y) => x.level - y.level);
          return (
            <Card key={b.id}>
              <Group justify="space-between" mb="sm" wrap="nowrap">
                <div>
                  <Group gap="xs">
                    <Text fw={650}>{b.name}</Text>
                    <Badge variant="outline" color="gray" radius="sm">
                      {b.code}
                    </Badge>
                    {!b.is_active && <ActiveBadge active={false} />}
                  </Group>
                  <Text size="xs" c="dimmed">
                    {t('settings.structure.floor_count', { count: bFloors.length })}
                  </Text>
                </div>
                {canEdit && (
                  <Group gap={4} wrap="nowrap">
                    <ActionIcon variant="subtle" aria-label={t('common.edit')} onClick={() => setBuildingDraft({ ...b })}>
                      <IconEdit size={16} />
                    </ActionIcon>
                    <ActionIcon
                      variant="subtle"
                      color="red"
                      aria-label={t('common.delete')}
                      onClick={() =>
                        confirmDelete({
                          title: t('settings.structure.delete_building', { name: b.name }),
                          onConfirm: () => buildingCrud.remove.mutateAsync(b.id).then(() => notifySuccess(t('common.deleted')), notifyError),
                        })
                      }
                    >
                      <IconTrash size={16} />
                    </ActionIcon>
                  </Group>
                )}
              </Group>
              <Table>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>{t('settings.structure.level')}</Table.Th>
                    <Table.Th>{t('common.name')}</Table.Th>
                    <Table.Th ta="right">{t('settings.structure.rooms')}</Table.Th>
                    {canEdit && <Table.Th w={80} />}
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {bFloors.map((f) => (
                    <Table.Tr key={f.id}>
                      <Table.Td className="hms-num">{f.level}</Table.Td>
                      <Table.Td>{f.name}</Table.Td>
                      <Table.Td ta="right" className="hms-num">
                        {roomsOnFloor(f.id)}
                      </Table.Td>
                      {canEdit && (
                        <Table.Td>
                          <Group gap={4} justify="flex-end" wrap="nowrap">
                            <ActionIcon variant="subtle" size="sm" aria-label={t('common.edit')} onClick={() => setFloorDraft({ ...f })}>
                              <IconEdit size={14} />
                            </ActionIcon>
                            <ActionIcon
                              variant="subtle"
                              size="sm"
                              color="red"
                              aria-label={t('common.delete')}
                              onClick={() =>
                                confirmDelete({
                                  title: t('settings.structure.delete_floor', { name: f.name }),
                                  onConfirm: () => floorCrud.remove.mutateAsync(f.id).then(() => notifySuccess(t('common.deleted')), notifyError),
                                })
                              }
                            >
                              <IconTrash size={14} />
                            </ActionIcon>
                          </Group>
                        </Table.Td>
                      )}
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
              {canEdit && (
                <Button
                  variant="subtle"
                  size="xs"
                  mt="xs"
                  leftSection={<IconPlus size={14} />}
                  onClick={() => {
                    const next = bFloors.length ? Math.max(...bFloors.map((f) => f.level)) + 1 : 0;
                    setFloorDraft({ building_id: b.id, level: next, name: t('settings.structure.default_floor_name', { level: next }), sort_order: 0 });
                  }}
                >
                  {t('settings.structure.add_floor')}
                </Button>
              )}
            </Card>
          );
        })}
      </SimpleGrid>

      {buildingDraft && <BuildingModal draft={buildingDraft} crud={buildingCrud} onClose={() => setBuildingDraft(null)} />}
      {floorDraft && <FloorModal draft={floorDraft} crud={floorCrud} onClose={() => setFloorDraft(null)} />}
    </Stack>
  );
}

function BuildingModal({ draft, crud, onClose }: { draft: BuildingDraft; crud: ReturnType<typeof useCrud<Building>>; onClose: () => void }) {
  const { t } = useTranslation();
  const form = useForm({ initialValues: draft });
  const submit = form.onSubmit(async ({ id, version, ...values }) => {
    try {
      if (id) await crud.update.mutateAsync({ id, body: { ...values, version } });
      else await crud.create.mutateAsync(values);
      notifySuccess(t('common.saved'));
      onClose();
    } catch (err) {
      if (!applyFieldErrors(err, form.setFieldError)) notifyError(err);
    }
  });
  return (
    <Modal opened onClose={onClose} title={draft.id ? t('settings.structure.edit_building') : t('settings.structure.add_building')}>
      <form onSubmit={submit}>
        <Stack>
          <TextInput label={t('common.code')} description={t('common.code_hint')} required {...form.getInputProps('code')} />
          <TextInput label={t('common.name')} required {...form.getInputProps('name')} />
          <NumberInput label={t('common.sort_order')} min={0} {...form.getInputProps('sort_order')} />
          <Switch label={t('common.active')} {...form.getInputProps('is_active', { type: 'checkbox' })} />
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

function FloorModal({ draft, crud, onClose }: { draft: FloorDraft; crud: ReturnType<typeof useCrud<Floor>>; onClose: () => void }) {
  const { t } = useTranslation();
  const form = useForm({ initialValues: draft });
  const submit = form.onSubmit(async ({ id, version, building_id, ...values }) => {
    try {
      if (id) await crud.update.mutateAsync({ id, body: { ...values, version } });
      else await crud.create.mutateAsync({ building_id, ...values });
      notifySuccess(t('common.saved'));
      onClose();
    } catch (err) {
      if (!applyFieldErrors(err, form.setFieldError)) notifyError(err);
    }
  });
  return (
    <Modal opened onClose={onClose} title={draft.id ? t('settings.structure.edit_floor') : t('settings.structure.add_floor')}>
      <form onSubmit={submit}>
        <Stack>
          <NumberInput label={t('settings.structure.level')} description={t('settings.structure.level_hint')} min={-10} max={300} required {...form.getInputProps('level')} />
          <TextInput label={t('common.name')} required {...form.getInputProps('name')} />
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
