import { lazy, Suspense, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router';
import { Button, Drawer, Tabs, Title } from '@mantine/core';
import { IconCalendarTime, IconListDetails, IconMotorbike, IconPlus } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { PageLoader } from '@/app/AppLayout';
import { useAuth } from '@/auth/AuthProvider';
import { PageHeader } from '@/components/ui';
import { NewRentalDrawer, type RentalDraft } from './NewRentalDrawer';
import { RentalDetail } from './RentalDrawer';

const TABS = {
  today: { icon: IconListDetails, perm: 'vehicles.view', Component: lazy(() => import('./TodayTab')) },
  schedule: { icon: IconCalendarTime, perm: 'vehicles.view', Component: lazy(() => import('./ScheduleTab')) },
  fleet: { icon: IconMotorbike, perm: 'vehicles.view', Component: lazy(() => import('./FleetTab')) },
} as const;
type TabKey = keyof typeof TABS;

export interface RentalActions {
  open: (id: string) => void;
  create: (draft?: RentalDraft) => void;
}

export default function VehiclesPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const params = useParams();
  const navigate = useNavigate();
  const [search, setSearch] = useSearchParams();
  const tab = ((params['*'] ?? '') in TABS ? params['*'] : 'today') as TabKey;
  const { Component } = TABS[tab];
  const [draft, setDraft] = useState<RentalDraft | null>(null);
  const selected = search.get('rental');
  const select = (id: string | null) =>
    setSearch(
      (p) => {
        const out = new URLSearchParams(p);
        if (id) out.set('rental', id);
        else out.delete('rental');
        return out;
      },
      { replace: true },
    );
  const actions: RentalActions = { open: select, create: (d) => setDraft(d ?? {}) };
  return (
    <>
      <PageHeader
        title={t('nav.vehicles')}
        description={t('vehicles.description')}
        actions={
          can('vehicles.rent') && (
            <Button leftSection={<IconPlus size={16} />} onClick={() => setDraft({})}>
              {t('vehicles.new_rental')}
            </Button>
          )
        }
      />
      <Tabs value={tab} onChange={(v) => v && navigate({ pathname: `/vehicles/${v}`, search: search.toString() })} keepMounted={false} mb="md">
        <Tabs.List>
          {(Object.keys(TABS) as TabKey[]).map((k) => {
            const Icon = TABS[k].icon;
            return (
              <Tabs.Tab key={k} value={k} leftSection={<Icon size={16} />}>
                {t(`vehicles.tabs.${k}`)}
              </Tabs.Tab>
            );
          })}
        </Tabs.List>
      </Tabs>
      <Suspense fallback={<PageLoader />}>
        <Component actions={actions} />
      </Suspense>
      <NewRentalDrawer draft={draft} onClose={() => setDraft(null)} onCreated={(id) => select(id)} />
      <Drawer opened={!!selected} onClose={() => select(null)} position="right" size="lg" title={<Title order={3}>{t('vehicles.rental')}</Title>}>
        {selected && <RentalDetail id={selected} />}
      </Drawer>
    </>
  );
}
