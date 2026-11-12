import { useState } from 'react';
import { ActionIcon, Badge, Button, Group, Menu, Modal, MultiSelect, PasswordInput, Select, Stack, Switch, Table, Text, TextInput } from '@mantine/core';
import { useForm } from '@mantine/form';
import { IconDots, IconEdit, IconKey, IconLockOpen, IconPlus } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { api } from '@/api/client';
import { useHotelMutation, useHotelQuery } from '@/api/hooks';
import type { AdminUser, Role } from '@/api/types';
import { useAuth, useHotel } from '@/auth/AuthProvider';
import { ActiveBadge, SubmitButton } from '@/components/ui';
import { LANGUAGES } from '@/i18n';
import { applyFieldErrors, notifyError, notifySuccess } from '@/lib/errors';
import { formatDateTime } from '@/lib/format';
import { useRoleName } from './roles';

export default function UsersTab() {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const { can, me } = useAuth();
  const canManage = can('users.manage');
  const users = useHotelQuery<AdminUser[]>('user', '/users');
  const roles = useHotelQuery<Role[]>('role', '/roles');
  const roleName = useRoleName();
  const [editing, setEditing] = useState<AdminUser | 'new' | null>(null);
  const [resetting, setResetting] = useState<AdminUser | null>(null);
  const unlock = useHotelMutation<string, AdminUser>((h, id) => api.post<AdminUser>(h(`/users/${id}/unlock`)), ['user']);

  const roleById = new Map((roles.data ?? []).map((r) => [r.id, r]));

  return (
    <Stack>
      {canManage && (
        <Group justify="flex-end">
          <Button leftSection={<IconPlus size={16} />} onClick={() => setEditing('new')}>
            {t('users.add')}
          </Button>
        </Group>
      )}
      <div className="hms-table-wrap">
        <Table miw={760}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t('users.user')}</Table.Th>
              <Table.Th>{t('users.roles')}</Table.Th>
              <Table.Th>{t('users.last_login')}</Table.Th>
              <Table.Th>{t('users.security')}</Table.Th>
              <Table.Th>{t('common.status')}</Table.Th>
              {canManage && <Table.Th w={50} />}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {users.data?.map((u) => {
              const locked = u.locked_until && new Date(u.locked_until) > new Date();
              return (
                <Table.Tr key={u.id}>
                  <Table.Td>
                    <Text size="sm" fw={600}>
                      {u.full_name} {u.id === me?.user.id && <Badge size="xs" variant="light">{t('users.you')}</Badge>}
                    </Text>
                    <Text size="xs" c="dimmed">
                      {u.email}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Group gap={4}>
                      {u.is_superadmin && (
                        <Badge color="brass" variant="light" radius="sm">
                          {t('roles.system.super_admin')}
                        </Badge>
                      )}
                      {u.role_ids.map((id) => {
                        const r = roleById.get(id);
                        return r ? (
                          <Badge key={id} variant="light" color="gray" radius="sm">
                            {roleName(r)}
                          </Badge>
                        ) : null;
                      })}
                    </Group>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">{formatDateTime(u.last_login_at, i18n.language, hotel.timezone)}</Text>
                    {u.active_sessions > 0 && (
                      <Text size="xs" c="dimmed">
                        {t('users.active_sessions', { count: u.active_sessions })}
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td>
                    <Group gap={4}>
                      {u.totp_enabled && (
                        <Badge variant="outline" color="lagoon" radius="sm">
                          2FA
                        </Badge>
                      )}
                      {locked && (
                        <Badge variant="filled" color="red" radius="sm">
                          {t('users.locked')}
                        </Badge>
                      )}
                    </Group>
                  </Table.Td>
                  <Table.Td>
                    <ActiveBadge active={u.is_active} />
                  </Table.Td>
                  {canManage && (
                    <Table.Td>
                      <Menu position="bottom-end">
                        <Menu.Target>
                          <ActionIcon variant="subtle" aria-label={t('common.actions')}>
                            <IconDots size={16} />
                          </ActionIcon>
                        </Menu.Target>
                        <Menu.Dropdown>
                          <Menu.Item leftSection={<IconEdit size={14} />} onClick={() => setEditing(u)}>
                            {t('common.edit')}
                          </Menu.Item>
                          <Menu.Item leftSection={<IconKey size={14} />} onClick={() => setResetting(u)}>
                            {t('users.reset_password')}
                          </Menu.Item>
                          {locked && (
                            <Menu.Item
                              leftSection={<IconLockOpen size={14} />}
                              onClick={() => unlock.mutateAsync(u.id).then(() => notifySuccess(t('users.unlocked')), notifyError)}
                            >
                              {t('users.unlock')}
                            </Menu.Item>
                          )}
                        </Menu.Dropdown>
                      </Menu>
                    </Table.Td>
                  )}
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>
      </div>
      {editing && <UserModal user={editing === 'new' ? null : editing} roles={roles.data ?? []} onClose={() => setEditing(null)} />}
      {resetting && <ResetPasswordModal user={resetting} onClose={() => setResetting(null)} />}
    </Stack>
  );
}

function UserModal({ user, roles, onClose }: { user: AdminUser | null; roles: Role[]; onClose: () => void }) {
  const { t } = useTranslation();
  const { me } = useAuth();
  const roleName = useRoleName();
  const form = useForm({
    initialValues: {
      email: user?.email ?? '',
      full_name: user?.full_name ?? '',
      password: '',
      preferred_language: user?.preferred_language ?? 'en',
      is_active: user?.is_active ?? true,
      role_ids: user?.role_ids ?? [],
    },
  });
  const save = useHotelMutation<typeof form.values, AdminUser>(async (h, values) => {
    if (!user) {
      return api.post<AdminUser>(h('/users'), values);
    }
    const updated = await api.patch<AdminUser>(h(`/users/${user.id}`), {
      version: user.version,
      full_name: values.full_name,
      preferred_language: values.preferred_language,
      is_active: values.is_active,
    });
    const sameRoles = [...values.role_ids].sort().join() === [...user.role_ids].sort().join();
    return sameRoles ? updated : api.put<AdminUser>(h(`/users/${user.id}/roles`), { role_ids: values.role_ids });
  }, ['user', 'role', 'session']);

  const submit = form.onSubmit(async (values) => {
    try {
      await save.mutateAsync(values);
      notifySuccess(t('common.saved'));
      onClose();
    } catch (err) {
      if (!applyFieldErrors(err, form.setFieldError)) notifyError(err);
    }
  });
  const isSelf = user?.id === me?.user.id;

  return (
    <Modal opened onClose={onClose} title={user ? t('users.edit') : t('users.add')} size="lg">
      <form onSubmit={submit}>
        <Stack>
          <TextInput label={t('auth.email')} type="email" required disabled={!!user} {...form.getInputProps('email')} />
          <TextInput label={t('users.full_name')} required {...form.getInputProps('full_name')} />
          {!user && <PasswordInput label={t('users.initial_password')} description={t('users.password_policy')} required {...form.getInputProps('password')} />}
          <Select
            label={t('users.language')}
            allowDeselect={false}
            data={LANGUAGES.map((l) => ({ value: l.code, label: l.label }))}
            {...form.getInputProps('preferred_language')}
          />
          <MultiSelect
            label={t('users.roles_in_hotel')}
            disabled={isSelf}
            description={isSelf ? t('users.cannot_change_own_roles') : undefined}
            data={roles.map((r) => ({ value: r.id, label: roleName(r) }))}
            {...form.getInputProps('role_ids')}
          />
          {user && <Switch label={t('users.account_active')} disabled={isSelf} {...form.getInputProps('is_active', { type: 'checkbox' })} />}
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <SubmitButton loading={save.isPending}>{t('common.save')}</SubmitButton>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

function ResetPasswordModal({ user, onClose }: { user: AdminUser; onClose: () => void }) {
  const { t } = useTranslation();
  const form = useForm({ initialValues: { new_password: '' } });
  const reset = useHotelMutation<string, void>((h, pw) => api.post(h(`/users/${user.id}/password`), { new_password: pw }), ['user', 'session']);
  const submit = form.onSubmit(async ({ new_password }) => {
    try {
      await reset.mutateAsync(new_password);
      notifySuccess(t('users.password_reset_done'));
      onClose();
    } catch (err) {
      if (!applyFieldErrors(err, form.setFieldError)) notifyError(err);
    }
  });
  return (
    <Modal opened onClose={onClose} title={t('users.reset_password_for', { name: user.full_name })}>
      <form onSubmit={submit}>
        <Stack>
          <Text size="sm" c="dimmed">
            {t('users.reset_password_hint')}
          </Text>
          <PasswordInput label={t('users.new_password')} description={t('users.password_policy')} required {...form.getInputProps('new_password')} />
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <SubmitButton loading={reset.isPending}>{t('users.reset_password')}</SubmitButton>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}
