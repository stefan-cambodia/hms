import { lazy, Suspense, useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import { Group, Select, Tabs } from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import { IconChartLine, IconTelescope } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { PageLoader } from '@/app/AppLayout';
import { useHotel } from '@/auth/AuthProvider';
import { PageHeader } from '@/components/ui';
import { addDays, hotelToday } from '@/lib/dates';
import { type Compare, type Preset, presetRange } from './shared';

const PerformanceTab = lazy(() => import('./PerformanceTab'));
const ForecastTab = lazy(() => import('./ForecastTab'));

const PRESETS: Preset[] = ['this_month', 'last_month', 'last_30', 'this_year', 'custom'];

export default function ReportsPage() {
  const { t } = useTranslation();
  const hotel = useHotel();
  const params = useParams();
  const navigate = useNavigate();
  const tab = params['*'] === 'forecast' ? 'forecast' : 'performance';
  const today = hotelToday(hotel.timezone);
  const [preset, setPreset] = useState<Preset>('this_month');
  const [custom, setCustom] = useState<[string | null, string | null]>([addDays(today, -7), addDays(today, -1)]);
  const [compare, setCompare] = useState<Compare>('previous');
  // The API takes [start, end) — the picker shows the last night included.
  const [start, end] =
    preset === 'custom' ? (custom[0] && custom[1] ? [custom[0], addDays(custom[1], 1)] : [null, null]) : presetRange(preset, today);

  return (
    <>
      <PageHeader title={t('nav.reports')} description={t('reports.description')} />
      <Tabs value={tab} onChange={(v) => v && navigate(`/reports/${v === 'performance' ? '' : v}`)} keepMounted={false} mb="md">
        <Tabs.List>
          <Tabs.Tab value="performance" leftSection={<IconChartLine size={16} />}>
            {t('reports.tabs.performance')}
          </Tabs.Tab>
          <Tabs.Tab value="forecast" leftSection={<IconTelescope size={16} />}>
            {t('reports.tabs.forecast')}
          </Tabs.Tab>
        </Tabs.List>
      </Tabs>
      <Suspense fallback={<PageLoader />}>
        {tab === 'performance' ? (
          <>
            {/* One filter row above everything it scopes. */}
            <Group gap="sm" mb="md" align="flex-end" wrap="wrap">
              <Select
                label={t('reports.range')}
                w={200}
                allowDeselect={false}
                value={preset}
                onChange={(v) => v && setPreset(v as Preset)}
                data={PRESETS.map((p) => ({ value: p, label: t(`reports.presets.${p}`) }))}
                data-testid="range-preset"
              />
              {preset === 'custom' && (
                <DatePickerInput
                  type="range"
                  label={t('reports.custom_range')}
                  w={260}
                  value={custom}
                  onChange={(v) => setCustom(v as [string | null, string | null])}
                  valueFormat="D MMM YYYY"
                  allowSingleDateInRange
                />
              )}
              <Select
                label={t('reports.compare')}
                w={220}
                allowDeselect={false}
                value={compare}
                onChange={(v) => v && setCompare(v as Compare)}
                data={(['none', 'previous', 'last_year'] as Compare[]).map((c) => ({ value: c, label: t(`reports.compare_with.${c}`) }))}
              />
            </Group>
            {start && end && <PerformanceTab start={start} end={end} compare={compare} />}
          </>
        ) : (
          <ForecastTab />
        )}
      </Suspense>
    </>
  );
}
