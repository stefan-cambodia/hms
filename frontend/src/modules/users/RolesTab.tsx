import { useState } from 'react';
import { Accordion, ActionIcon, Badge, Button, Card, Checkbox, Drawer, Group, SimpleGrid, Stack, Text, Textarea, TextInput } from '@mantine/core';
import { useForm } from '@mantine/form';
import { IconCopy, IconEdit, IconLock, IconPlus, IconTrash } from '@tabler/icons-react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { api } from '@/api/client';
import { useCrud, useHotelQuery } from '@/api/hooks';
import type { PermissionGroup, Role } from '@/api/types';
import { useAuth } from '@/auth/AuthProvider';
import { confirmDelete, SubmitButton } from '@/components/ui';
import { applyFieldErrors, notifyError, notifySuccess } from '@/lib/errors';
import { useRoleName } from './roles';

interface Draft {
  id?: string;
  version?: number;
  code: string;
  name: string;
  description: string;
  permissions: string[];
}

export default function RolesTab() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const canManage = can('roles.manage');
  const roles = useHotelQuery<Role[]>('role', '/roles');
  const crud = useCrud<Role>('role', '/roles', ['role', 'user']);
  const roleName = useRoleName();
  const [draft, setDraft] = useState<Draft | null>(null);

  return (
    <Stack>
      <Group justify="space-between">
        <Text size="sm" c="dimmed" maw={640}>
          {t('roles.hint')}
        </Text>
        {canManage && (
          <Button leftSection={<IconPlus size={16} />} onClick={() => setDraft({ code: '', name: '', description: '', permissions: [] })}>
            {t('roles.add')}
          </Button>
        )}
      </Group>
      <SimpleGrid cols={{ base: 1, md: 2, xl: 3 }}>
        {roles.data?.map((r) => (
          <Card key={r.id}>
            <Group justify="space-between" align="flex-start" wrap="nowrap">
              <div>
                <Group gap={6}>
                  <Text fw={650}>{roleName(r)}</Text>
                  {r.is_system && (
                    <Badge size="xs" variant="light" color="gray" leftSection={<IconLock size={10} />}>
                      {t('roles.system_role')}
                    </Badge>
                  )}
                </Group>
                <Text size="xs" c="dimmed">
                  {t('roles.summary', { permissions: r.permissions.length, users: r.user_count })}
                </Text>
              </div>
              {canManage && (
                <Group gap={4} wrap="nowrap">
                  <ActionIcon
                    variant="subtle"
                    aria-label={t('roles.duplicate')}
                    onClick={() => setDraft({ code: `${r.code}_copy`, name: `${roleName(r)} (2)`, description: r.description ?? '', permissions: r.permissions })}
                  >
                    <IconCopy size={16} />
                  </ActionIcon>
                  {!r.is_system && (
                    <>
                      <ActionIcon variant="subtle" aria-label={t('common.edit')} onClick={() => setDraft({ ...r, description: r.description ?? '' })}>
                        <IconEdit size={16} />
                      </ActionIcon>
                      <ActionIcon
                        variant="subtle"
                        color="red"
                        aria-label={t('common.delete')}
                        onClick={() =>
                          confirmDelete({
                            title: t('roles.delete', { name: r.name }),
                            onConfirm: () => crud.remove.mutateAsync(r.id).then(() => notifySuccess(t('common.deleted')), notifyError),
                          })
                        }
                      >
                        <IconTrash size={16} />
                      </ActionIcon>
                    </>
                  )}
                </Group>
              )}
            </Group>
            {r.description && (
              <Text size="sm" mt="xs">
                {r.description}
              </Text>
            )}
          </Card>
        ))}
      </SimpleGrid>
      {draft && <RoleDrawer draft={draft} crud={crud} onClose={() => setDraft(null)} />}
    </Stack>
  );
}

function RoleDrawer({ draft, crud, onClose }: { draft: Draft; crud: ReturnType<typeof useCrud<Role>>; onClose: () => void }) {
  const { t } = useTranslation();
  const { hotel, me } = useAuth();
  const catalog = useQuery({ queryKey: ['permissions'], queryFn: () => api.get<PermissionGroup[]>('/permissions'), staleTime: Infinity });
  const form = useForm<Draft>({ initialValues: draft });
  const selected = new Set(form.getValues().permissions);
  // You can only grant what you hold yourself (enforced server-side too).
  const grantable = (p: string) => me?.user.is_superadmin || !!hotel?.permissions.includes(p);

  const toggle = (p: string, on: boolean) => {
    const next = new Set(selected);
    if (on) next.add(p);
    else next.delete(p);
    form.setFieldValue('permissions', [...next].sort());
  };

  const submit = form.onSubmit(async ({ id, version, ...values }) => {
    const body = { ...values, description: values.description || null };
    try {
      if (id) await crud.update.mutateAsync({ id, body: { name: body.name, description: body.description, permissions: body.permissions, version } });
      else await crud.create.mutateAsync(body as never);
      notifySuccess(t('common.saved'));
      onClose();
    } catch (err) {
      if (!applyFieldErrors(err, form.setFieldError)) notifyError(err);
    }
  });

  return (
    <Drawer opened onClose={onClose} title={draft.id ? t('roles.edit') : t('roles.add')} size="xl">
      <form onSubmit={submit}>
        <Stack>
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <TextInput label={t('common.code')} required disabled={!!draft.id} {...form.getInputProps('code')} />
            <TextInput label={t('common.name')} required {...form.getInputProps('name')} />
          </SimpleGrid>
          <Textarea label={t('common.description')} autosize minRows={2} {...form.getInputProps('description')} />
          <Text fw={600} size="sm">
            {t('roles.permissions', { count: selected.size })}
          </Text>
          <Accordion variant="separated" multiple defaultValue={catalog.data?.map((g) => g.group)}>
            {catalog.data?.map((g) => {
              const all = g.permissions.filter(grantable);
              const on = g.permissions.filter((p) => selected.has(p)).length;
              return (
                <Accordion.Item key={g.group} value={g.group}>
                  <Accordion.Control>
                    <Group justify="space-between" pr="sm">
                      <Text size="sm" fw={600}>
                        {t(`permissions.groups.${g.group}`)}
                      </Text>
                      <Badge variant="light" color={on ? 'lagoon' : 'gray'} radius="sm">
                        {on}/{g.permissions.length}
                      </Badge>
                    </Group>
                  </Accordion.Control>
                  <Accordion.Panel>
                    <Stack gap={8}>
                      <Checkbox
                        size="xs"
                        label={t('roles.select_all')}
                        checked={all.length > 0 && all.every((p) => selected.has(p))}
                        indeterminate={on > 0 && on < all.length}
                        onChange={(e) => all.forEach((p) => toggle(p, e.currentTarget.checked))}
                      />
                      {g.permissions.map((p) => (
                        <Checkbox
                          key={p}
                          label={t(`permissions.codes.${p.replace(/\./g, '_')}`)}
                          description={!grantable(p) ? t('roles.not_grantable') : undefined}
                          disabled={!grantable(p)}
                          checked={selected.has(p)}
                          onChange={(e) => toggle(p, e.currentTarget.checked)}
                        />
                      ))}
                    </Stack>
                  </Accordion.Panel>
                </Accordion.Item>
              );
            })}
          </Accordion>
          <Group justify="flex-end" mt="md">
            <Button variant="default" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <SubmitButton loading={crud.create.isPending || crud.update.isPending}>{t('common.save')}</SubmitButton>
          </Group>
        </Stack>
      </form>
    </Drawer>
  );
}
