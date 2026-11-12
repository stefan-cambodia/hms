import { lazy, Suspense } from 'react';
import { useNavigate, useParams } from 'react-router';
import { Tabs } from '@mantine/core';
import { IconHistory, IconKey, IconPlugConnected, IconShieldLock, IconUsers } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { PageLoader } from '@/app/AppLayout';
import { useAuth } from '@/auth/AuthProvider';
import { PageHeader } from '@/components/ui';

const TABS = {
  list: { icon: IconUsers, permission: 'users.view', Component: lazy(() => import('./UsersTab')) },
  roles: { icon: IconShieldLock, permission: 'users.view', Component: lazy(() => import('./RolesTab')) },
  sessions: { icon: IconPlugConnected, permission: 'sessions.manage', Component: lazy(() => import('./SessionsTab')) },
  logins: { icon: IconKey, permission: 'sessions.manage', Component: lazy(() => import('./LoginHistoryTab')) },
  audit: { icon: IconHistory, permission: 'audit.view', Component: lazy(() => import('./AuditTab')) },
} as const;
type TabKey = keyof typeof TABS;

export default function UsersPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const params = useParams();
  const navigate = useNavigate();
  const allowed = (Object.keys(TABS) as TabKey[]).filter((k) => can(TABS[k].permission));
  const requested = (params['*'] || 'list') as TabKey;
  const active = allowed.includes(requested) ? requested : allowed[0];
  if (!active) return null;
  const { Component } = TABS[active];

  return (
    <>
      <PageHeader title={t('nav.users')} description={t('users.description')} />
      <Tabs value={active} onChange={(v) => v && navigate(`/users/${v}`)} keepMounted={false} mb="lg">
        <Tabs.List style={{ overflowX: 'auto', flexWrap: 'nowrap' }}>
          {allowed.map((key) => {
            const Icon = TABS[key].icon;
            return (
              <Tabs.Tab key={key} value={key} leftSection={<Icon size={16} />}>
                {t(`users.tabs.${key}`)}
              </Tabs.Tab>
            );
          })}
        </Tabs.List>
      </Tabs>
      <Suspense fallback={<PageLoader />}>
        <Component />
      </Suspense>
    </>
  );
}
