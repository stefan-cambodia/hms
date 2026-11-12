import { useState } from 'react';
import { Button, Group, Loader, SegmentedControl, SimpleGrid, Stack, Table, Text } from '@mantine/core';
import { IconDownload } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { useHotelQuery } from '@/api/hooks';
import type { ForecastReport } from '@/api/types';
import { ChartCard, ColumnChart } from '@/components/charts';
import { downloadCsv, toCsv } from '@/lib/csv';
import { StatTile, useFormatters } from './shared';

const HORIZONS = [30, 60, 90, 180] as const;

export default function ForecastTab() {
  const { t, i18n } = useTranslation();
  const [days, setDays] = useState<number>(30);
  const [view, setView] = useState<'chart' | 'table'>('chart');
  const report = useHotelQuery<ForecastReport>('report', '/reports/forecast', { days });
  const r = report.data;
  const f = useFormatters(r?.currency ?? 'USD');
  if (report.isPending || !r) return <Loader size="sm" />;
  const fin = r.financial;
  const share = (n: number, available: number) => (available > 0 ? (n * 100) / available : 0);
  const earlier = r.daily.map((d) => share(d.sold - d.pickup, d.available));
  const recent = r.daily.map((d) => share(d.pickup, d.available));

  const exportCsv = () =>
    downloadCsv(
      `forecast-${r.start}-${days}.csv`,
      toCsv(
        [t('reports.night'), t('reports.available'), t('reports.on_books'), `${t('reports.occupancy')} %`, t('reports.pickup_7d'), ...(fin ? [`${t('reports.revenue')} (${r.currency})`, `ADR (${r.currency})`] : [])],
        r.daily.map((d) => [d.date, d.available, d.sold, d.occupancy, d.pickup, ...(fin ? [d.revenue, d.adr] : [])]),
        i18n.language,
      ),
    );

  return (
    <Stack gap="lg" style={{ opacity: report.isFetching ? 0.6 : 1, transition: 'opacity 120ms' }} data-testid="forecast">
      <Group justify="space-between">
        <SegmentedControl
          value={String(days)}
          onChange={(v) => setDays(Number(v))}
          data={HORIZONS.map((h) => ({ value: String(h), label: t('reports.next_days', { count: h }) }))}
        />
        <Button variant="default" size="xs" leftSection={<IconDownload size={14} />} onClick={exportCsv}>
          {t('reports.export')}
        </Button>
      </Group>
      <SimpleGrid cols={{ base: 2, md: fin ? 4 : 3 }} spacing="sm">
        <StatTile testId="forecast-occupancy" label={t('reports.occupancy_on_books')} value={f.pct(r.totals.occupancy)} sub={t('reports.sold_of', { sold: f.num(r.totals.sold), available: f.num(r.totals.available) })} />
        <StatTile label={t('reports.on_books')} value={f.num(r.totals.sold)} />
        <StatTile label={t('reports.pickup_7d')} value={f.num(r.totals.pickup)} sub={t('reports.pickup_hint')} />
        {fin && <StatTile label={t('reports.revenue_on_books')} value={f.money(r.totals.revenue)} sub={`${t('reports.adr')} ${f.money(r.totals.adr)}`} />}
      </SimpleGrid>
      <ChartCard
        title={t('reports.occupancy_on_books')}
        subtitle={t('reports.forecast_hint')}
        actions={
          <SegmentedControl
            size="xs"
            value={view}
            onChange={(v) => setView(v as typeof view)}
            data={[
              { value: 'chart', label: t('reports.view_chart') },
              { value: 'table', label: t('reports.view_table') },
            ]}
          />
        }
      >
        {view === 'chart' ? (
          <ColumnChart
            labels={r.daily.map((d) => f.shortDate(d.date))}
            titles={r.daily.map((d) => f.longDate(d.date))}
            series={[
              { label: t('reports.booked_earlier'), tone: 'muted', values: earlier },
              { label: t('reports.picked_up'), tone: 'accent', values: recent },
            ]}
            format={(v) => `${f.num(v)} %`}
            yMax={100}
            ariaLabel={t('reports.occupancy_on_books')}
            footer={(i) => ({ label: t('reports.rooms_sold'), value: `${r.daily[i].sold} / ${r.daily[i].available}` })}
          />
        ) : (
          <Table.ScrollContainer minWidth={560} mah={380}>
            <Table striped stickyHeader verticalSpacing={4} className="hms-num" data-testid="forecast-table">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t('reports.night')}</Table.Th>
                  <Table.Th ta="right">{t('reports.available')}</Table.Th>
                  <Table.Th ta="right">{t('reports.on_books')}</Table.Th>
                  <Table.Th ta="right">{t('reports.occupancy')}</Table.Th>
                  <Table.Th ta="right">{t('reports.pickup_7d')}</Table.Th>
                  {fin && <Table.Th ta="right">{t('reports.adr')}</Table.Th>}
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {r.daily.map((d) => (
                  <Table.Tr key={d.date}>
                    <Table.Td>{f.longDate(d.date)}</Table.Td>
                    <Table.Td ta="right">{d.available}</Table.Td>
                    <Table.Td ta="right">{d.sold}</Table.Td>
                    <Table.Td ta="right">{f.pct(d.occupancy)}</Table.Td>
                    <Table.Td ta="right">{d.pickup}</Table.Td>
                    {fin && <Table.Td ta="right">{f.money(d.adr)}</Table.Td>}
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}
        <Text size="xs" c="dimmed" mt="xs">
          {t('reports.table_hint')}
        </Text>
      </ChartCard>
    </Stack>
  );
}
