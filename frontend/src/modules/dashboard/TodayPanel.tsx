import { Link } from 'react-router';
import { Anchor, SimpleGrid, Skeleton, Stack } from '@mantine/core';
import { useTranslation } from 'react-i18next';

import { useHotelQuery } from '@/api/hooks';
import type { TodayReport } from '@/api/types';
import { useAuth } from '@/auth/AuthProvider';
import { ChartCard, ColumnChart } from '@/components/charts';
import { delta, StatTile, useFormatters } from '@/modules/reports/shared';

/** Today's figures for the dashboard (reports or reservations permission). */
export default function TodayPanel() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const today = useHotelQuery<TodayReport>('report', '/reports/today');
  const r = today.data;
  const f = useFormatters(r?.currency ?? 'USD');
  if (today.isPending) return <Skeleton h={120} mb="lg" />;
  if (!r) return null;
  const ly = r.month_to_date_last_year;
  const hasLastYear = ly.available > 0;
  const vs = t('reports.vs.last_year');
  return (
    <Stack gap="lg" mb="lg" data-testid="today-panel">
      <SimpleGrid cols={{ base: 2, lg: 4 }} spacing="sm">
        <StatTile testId="tonight-occupancy" label={t('dashboard.tonight')} value={f.pct(r.tonight.occupancy)} sub={t('reports.sold_of', { sold: r.tonight.sold, available: r.tonight.available })} />
        <StatTile testId="arrivals" label={t('dashboard.arrivals')} value={f.num(r.arrived + r.arrivals_due)} sub={t('dashboard.arrived_of', { done: r.arrived, due: r.arrivals_due })} />
        <StatTile label={t('dashboard.departures')} value={f.num(r.departed + r.departures_due)} sub={t('dashboard.departed_of', { done: r.departed, due: r.departures_due })} />
        <StatTile label={t('dashboard.in_house')} value={f.num(r.in_house)} sub={t('dashboard.in_house_hint')} />
      </SimpleGrid>
      {r.financial && (
        <SimpleGrid cols={{ base: 1, xs: 3 }} spacing="sm">
          <StatTile label={t('dashboard.mtd_occupancy')} value={f.pct(r.month_to_date.occupancy)} change={hasLastYear ? delta(r.month_to_date.occupancy, ly.occupancy, 'points', f.lang) : null} vsLabel={vs} />
          <StatTile label={t('dashboard.mtd_adr')} value={f.money(r.month_to_date.adr)} change={hasLastYear ? delta(r.month_to_date.adr, ly.adr, 'relative', f.lang) : null} vsLabel={vs} />
          <StatTile label={t('dashboard.mtd_revpar')} value={f.money(r.month_to_date.revpar)} change={hasLastYear ? delta(r.month_to_date.revpar, ly.revpar, 'relative', f.lang) : null} vsLabel={vs} />
        </SimpleGrid>
      )}
      <ChartCard
        title={t('dashboard.next_nights')}
        subtitle={t('dashboard.next_nights_hint')}
        actions={
          can('reports.view') && (
            <Anchor component={Link} to="/reports/forecast" size="sm">
              {t('dashboard.forecast_link')}
            </Anchor>
          )
        }
      >
        <ColumnChart
          height={170}
          labels={r.next_days.map((d) => f.shortDate(d.date))}
          titles={r.next_days.map((d) => f.longDate(d.date))}
          series={[{ label: t('reports.occupancy'), tone: 'accent', values: r.next_days.map((d) => (d.occupancy === null ? 0 : Number(d.occupancy))) }]}
          format={(v) => `${f.num(v)} %`}
          yMax={100}
          ariaLabel={t('dashboard.next_nights')}
          footer={(i) => ({ label: t('reports.rooms_sold'), value: `${r.next_days[i].sold} / ${r.next_days[i].available}` })}
        />
      </ChartCard>
    </Stack>
  );
}
