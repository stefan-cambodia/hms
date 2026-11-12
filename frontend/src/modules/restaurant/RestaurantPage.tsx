import { lazy, Suspense } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router';
import { Button, Group, SegmentedControl, Tabs } from '@mantine/core';
import { IconChartBar, IconChefHat, IconCoffee, IconLayoutGrid, IconSettings } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { PageLoader } from '@/app/AppLayout';
import { useAuth } from '@/auth/AuthProvider';
import { EmptyState, PageHeader } from '@/components/ui';
import { useLocalized, useOutlet } from './shared';

const TABS = {
  floor: { icon: IconLayoutGrid, perm: 'restaurant.view', Component: lazy(() => import('./FloorTab')) },
  kitchen: { icon: IconChefHat, perm: 'restaurant.view', Component: lazy(() => import('./KitchenTab')) },
  breakfast: { icon: IconCoffee, perm: 'restaurant.view', Component: lazy(() => import('./BreakfastTab')) },
  sales: { icon: IconChartBar, perm: 'restaurant.manage|reports.financial', Component: lazy(() => import('./SalesTab')) },
  setup: { icon: IconSettings, perm: 'restaurant.manage', Component: lazy(() => import('./SetupTab')) },
} as const;
type TabKey = keyof typeof TABS;

export default function RestaurantPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const params = useParams();
  const [search] = useSearchParams();
  const navigate = useNavigate();
  const loc = useLocalized();
  const { active, outlet, select, loading } = useOutlet();
  const allowed = (Object.keys(TABS) as TabKey[]).filter((k) => TABS[k].perm.split('|').some((p) => can(p)));
  const fallback: TabKey = can('restaurant.order') || can('restaurant.settle') ? 'floor' : can('restaurant.kitchen') ? 'kitchen' : allowed[0];
  const tab = (allowed.includes(params['*'] as TabKey) ? params['*'] : fallback) as TabKey;
  const { Component } = TABS[tab];
  const go = (key: string) => navigate({ pathname: `/restaurant/${key}`, search: search.toString() });

  if (loading) return <PageLoader />;
  const needsSetup = active.length === 0;
  return (
    <>
      <PageHeader
        title={t('nav.restaurant')}
        description={t('restaurant.description')}
        actions={
          active.length > 1 && (
            <SegmentedControl value={outlet?.id ?? ''} onChange={select} data={active.map((o) => ({ value: o.id, label: loc(o.name) }))} />
          )
        }
      />
      {needsSetup && tab !== 'setup' ? (
        <EmptyState
          title={t('restaurant.no_outlet')}
          description={can('restaurant.manage') ? t('restaurant.no_outlet_hint') : undefined}
          action={
            can('restaurant.manage') && (
              <Button onClick={() => go('setup')}>{t('restaurant.setup_outlet')}</Button>
            )
          }
        />
      ) : (
        <>
          <Tabs value={tab} onChange={(v) => v && go(v)} keepMounted={false} mb="md">
            <Tabs.List style={{ overflowX: 'auto', flexWrap: 'nowrap' }}>
              {allowed.map((k) => {
                const Icon = TABS[k].icon;
                return (
                  <Tabs.Tab key={k} value={k} leftSection={<Icon size={16} />}>
                    {t(`restaurant.tabs.${k}`)}
                  </Tabs.Tab>
                );
              })}
            </Tabs.List>
          </Tabs>
          <Suspense fallback={<PageLoader />}>
            <Group display="block">
              <Component outletId={outlet?.id ?? null} />
            </Group>
          </Suspense>
        </>
      )}
    </>
  );
}
