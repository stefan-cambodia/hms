import { lazy, Suspense } from 'react';
import { useNavigate, useParams } from 'react-router';
import { Tabs } from '@mantine/core';
import { IconCalendarDollar, IconDiscount2, IconFileText, IconTags } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { PageLoader } from '@/app/AppLayout';
import { PageHeader } from '@/components/ui';

const TABS = {
  calendar: { icon: IconCalendarDollar, Component: lazy(() => import('./RateGridTab')) },
  plans: { icon: IconTags, Component: lazy(() => import('./RatePlansTab')) },
  rules: { icon: IconDiscount2, Component: lazy(() => import('./RulesTab')) },
  policies: { icon: IconFileText, Component: lazy(() => import('./PoliciesTab')) },
} as const;
type TabKey = keyof typeof TABS;

export default function PricingPage() {
  const { t } = useTranslation();
  const params = useParams();
  const navigate = useNavigate();
  const requested = (params['*'] || 'calendar') as TabKey;
  const active: TabKey = requested in TABS ? requested : 'calendar';
  const { Component } = TABS[active];
  return (
    <>
      <PageHeader title={t('nav.pricing')} description={t('pricing.description')} />
      <Tabs value={active} onChange={(v) => v && navigate(`/pricing/${v}`)} keepMounted={false} mb="lg">
        <Tabs.List style={{ overflowX: 'auto', flexWrap: 'nowrap' }}>
          {(Object.keys(TABS) as TabKey[]).map((key) => {
            const Icon = TABS[key].icon;
            return (
              <Tabs.Tab key={key} value={key} leftSection={<Icon size={16} />}>
                {t(`pricing.tabs.${key}`)}
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
