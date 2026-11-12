import { lazy, Suspense } from 'react';
import { useNavigate, useParams } from 'react-router';
import { Tabs } from '@mantine/core';
import { IconBed, IconBuilding, IconCurrencyDollar, IconHome, IconListCheck, IconReceiptTax } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { PageLoader } from '@/app/AppLayout';
import { PageHeader } from '@/components/ui';

const TABS = {
  profile: { icon: IconHome, Component: lazy(() => import('./HotelProfileTab')) },
  structure: { icon: IconBuilding, Component: lazy(() => import('./StructureTab')) },
  'room-types': { icon: IconBed, Component: lazy(() => import('./RoomTypesTab')) },
  amenities: { icon: IconListCheck, Component: lazy(() => import('./AmenitiesTab')) },
  taxes: { icon: IconReceiptTax, Component: lazy(() => import('./TaxesTab')) },
  currencies: { icon: IconCurrencyDollar, Component: lazy(() => import('./CurrenciesTab')) },
} as const;
type TabKey = keyof typeof TABS;

export default function SettingsPage() {
  const { t } = useTranslation();
  const params = useParams();
  const navigate = useNavigate();
  const active = ((params['*'] || 'profile') in TABS ? params['*'] || 'profile' : 'profile') as TabKey;
  const { Component } = TABS[active];

  return (
    <>
      <PageHeader title={t('nav.configuration')} description={t('settings.description')} />
      <Tabs value={active} onChange={(v) => v && navigate(`/settings/${v}`)} keepMounted={false} mb="lg">
        <Tabs.List style={{ overflowX: 'auto', flexWrap: 'nowrap' }}>
          {(Object.keys(TABS) as TabKey[]).map((key) => {
            const Icon = TABS[key].icon;
            return (
              <Tabs.Tab key={key} value={key} leftSection={<Icon size={16} />}>
                {t(`settings.tabs.${key}`)}
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
