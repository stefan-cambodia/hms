import { useState } from 'react';
import { Alert, Box, Button, Group, Loader, Menu, SegmentedControl, SimpleGrid, Stack, Table, Text } from '@mantine/core';
import { IconDownload } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { useHotelQuery } from '@/api/hooks';
import type { PerformanceReport, RatePlan, RoomType } from '@/api/types';
import { ChartCard, LineChart, Meter } from '@/components/charts';
import { downloadCsv, toCsv } from '@/lib/csv';
import { pickLocalized } from '@/lib/localized';
import { type Compare, delta, StatTile, useFormatters } from './shared';

type View = 'chart' | 'table';

function ViewToggle({ value, onChange }: { value: View; onChange: (v: View) => void }) {
  const { t } = useTranslation();
  return (
    <SegmentedControl
      size="xs"
      value={value}
      onChange={(v) => onChange(v as View)}
      data={[
        { value: 'chart', label: t('reports.view_chart') },
        { value: 'table', label: t('reports.view_table') },
      ]}
    />
  );
}

export default function PerformanceTab({ start, end, compare }: { start: string; end: string; compare: Compare }) {
  const { t, i18n } = useTranslation();
  const report = useHotelQuery<PerformanceReport>('report', '/reports/performance', { start, end, compare: compare === 'none' ? undefined : compare });
  const types = useHotelQuery<RoomType[]>('room_type', '/room-types');
  const plans = useHotelQuery<RatePlan[]>('rate_plan', '/rate-plans');
  const [occView, setOccView] = useState<View>('chart');
  const r = report.data;
  const f = useFormatters(r?.currency ?? 'USD');
  if (report.isPending || !r) return <Loader size="sm" />;

  const c = r.compare;
  const vs = c ? t(`reports.vs.${c.kind}`) : undefined;
  const fin = r.financial;
  const typeName = (id: string) => {
    const rt = types.data?.find((x) => x.id === id);
    return rt ? pickLocalized(rt.name, i18n.language) : '—';
  };
  const planName = (id: string | null) => {
    const p = plans.data?.find((x) => x.id === id);
    return p ? pickLocalized(p.name, i18n.language) : t('reports.no_plan');
  };
  const sourceName = (s: string) => t(`reservations.sources.${s}`, { defaultValue: s });
  const cur = r.currency;

  const exportDaily = () =>
    downloadCsv(
      `daily-${r.start}-${r.end}.csv`,
      toCsv(
        [t('reports.night'), t('reports.rooms'), t('reports.out_of_service'), t('reports.available'), t('reports.sold'), `${t('reports.occupancy')} %`, ...(fin ? [`${t('reports.revenue')} (${cur})`, `ADR (${cur})`, `RevPAR (${cur})`] : [])],
        r.daily.map((d) => [d.date, d.rooms, d.out_of_service, d.available, d.sold, d.occupancy, ...(fin ? [d.revenue, d.adr, d.revpar] : [])]),
        i18n.language,
      ),
    );
  const exportBreakdown = (kind: 'source' | 'room_type' | 'rate_plan') => {
    const header = [t(`reports.by.${kind}`), t('reports.sold'), `${t('reports.share')} %`, ...(fin ? [`${t('reports.revenue')} (${cur})`, `ADR (${cur})`] : [])];
    const rows =
      kind === 'source'
        ? r.by_source.map((x) => [sourceName(x.source), x.sold, x.share, ...(fin ? [x.revenue, x.adr] : [])])
        : kind === 'rate_plan'
          ? r.by_rate_plan.map((x) => [planName(x.rate_plan_id), x.sold, x.share, ...(fin ? [x.revenue, x.adr] : [])])
          : r.by_room_type.map((x) => [typeName(x.room_type_id), x.sold, x.occupancy, ...(fin ? [x.revenue, x.adr] : [])]);
    if (kind === 'room_type') header[2] = `${t('reports.occupancy')} %`;
    downloadCsv(`${kind}-${r.start}-${r.end}.csv`, toCsv(header, rows, i18n.language));
  };

  const titles = r.daily.map((d) => f.longDate(d.date));
  const labels = r.daily.map((d) => f.shortDate(d.date));
  const occSeries = [
    { label: t('reports.this_period'), tone: 'accent' as const, values: r.daily.map((d) => (d.occupancy === null ? null : Number(d.occupancy))) },
    ...(c ? [{ label: vs ?? '', tone: 'muted' as const, values: r.daily.map((_, i) => (c.daily[i]?.occupancy == null ? null : Number(c.daily[i].occupancy))) }] : []),
  ];
  const adrSeries = [
    { label: t('reports.this_period'), tone: 'accent' as const, values: r.daily.map((d) => (d.adr === null ? null : Number(d.adr))) },
    ...(c ? [{ label: vs ?? '', tone: 'muted' as const, values: r.daily.map((_, i) => (c.daily[i]?.adr == null ? null : Number(c.daily[i].adr))) }] : []),
  ];
  const roomRevenue = Number(r.totals.revenue ?? 0);
  const other = r.other_revenue;

  return (
    <Stack gap="lg" style={{ opacity: report.isFetching ? 0.6 : 1, transition: 'opacity 120ms' }} data-testid="performance">
      <Group justify="space-between">
        <Text size="sm" c="dimmed">
          {t('reports.period', { start: f.longDate(r.start), end: f.longDate(addDaysIso(r.end, -1)) })}
          {c && ` · ${t('reports.compared_with', { start: f.longDate(c.start), end: f.longDate(addDaysIso(c.end, -1)) })}`}
        </Text>
        <Menu position="bottom-end">
          <Menu.Target>
            <Button variant="default" size="xs" leftSection={<IconDownload size={14} />}>
              {t('reports.export')}
            </Button>
          </Menu.Target>
          <Menu.Dropdown>
            <Menu.Item onClick={exportDaily}>{t('reports.export_daily')}</Menu.Item>
            <Menu.Item onClick={() => exportBreakdown('source')}>{t('reports.export_by', { what: t('reports.by.source') })}</Menu.Item>
            <Menu.Item onClick={() => exportBreakdown('room_type')}>{t('reports.export_by', { what: t('reports.by.room_type') })}</Menu.Item>
            <Menu.Item onClick={() => exportBreakdown('rate_plan')}>{t('reports.export_by', { what: t('reports.by.rate_plan') })}</Menu.Item>
          </Menu.Dropdown>
        </Menu>
      </Group>

      <SimpleGrid cols={{ base: 2, md: 3, lg: fin ? 6 : 3 }} spacing="sm">
        <StatTile testId="kpi-occupancy" label={t('reports.occupancy')} value={f.pct(r.totals.occupancy)} sub={t('reports.sold_of', { sold: f.num(r.totals.sold), available: f.num(r.totals.available) })} change={c && delta(r.totals.occupancy, c.totals.occupancy, 'points', f.lang)} vsLabel={vs} />
        {fin && <StatTile testId="kpi-adr" label={t('reports.adr')} value={f.money(r.totals.adr)} change={c && delta(r.totals.adr, c.totals.adr, 'relative', f.lang)} vsLabel={vs} />}
        {fin && <StatTile testId="kpi-revpar" label={t('reports.revpar')} value={f.money(r.totals.revpar)} change={c && delta(r.totals.revpar, c.totals.revpar, 'relative', f.lang)} vsLabel={vs} />}
        {fin && <StatTile label={t('reports.room_revenue')} value={f.money(r.totals.revenue)} change={c && delta(r.totals.revenue, c.totals.revenue, 'relative', f.lang)} vsLabel={vs} />}
        <StatTile label={t('reports.room_nights')} value={f.num(r.totals.sold)} change={c && delta(r.totals.sold, c.totals.sold, 'relative', f.lang)} vsLabel={vs} />
        <StatTile
          label={t('reports.cancellation_rate')}
          value={f.pct(r.bookings.cancellation_rate)}
          sub={t('reports.cancelled_of', { cancelled: r.bookings.cancelled, created: r.bookings.created })}
          change={c && delta(r.bookings.cancellation_rate, c.bookings.cancellation_rate, 'points', f.lang, false)}
          vsLabel={vs}
        />
      </SimpleGrid>
      {!fin && <Alert color="gray">{t('reports.no_financial')}</Alert>}

      <ChartCard title={t('reports.occupancy_by_night')} subtitle={t('reports.occupancy_hint')} actions={<ViewToggle value={occView} onChange={setOccView} />}>
        {occView === 'chart' ? (
          <LineChart labels={labels} titles={titles} series={occSeries} format={(v) => `${f.num(v)} %`} yMax={100} ariaLabel={t('reports.occupancy_by_night')} area={!c} />
        ) : (
          <Table.ScrollContainer minWidth={640} mah={360}>
            <Table striped stickyHeader verticalSpacing={4} className="hms-num" data-testid="daily-table">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t('reports.night')}</Table.Th>
                  <Table.Th ta="right">{t('reports.available')}</Table.Th>
                  <Table.Th ta="right">{t('reports.sold')}</Table.Th>
                  <Table.Th ta="right">{t('reports.occupancy')}</Table.Th>
                  {fin && <Table.Th ta="right">{t('reports.adr')}</Table.Th>}
                  {fin && <Table.Th ta="right">{t('reports.revpar')}</Table.Th>}
                  {fin && <Table.Th ta="right">{t('reports.revenue')}</Table.Th>}
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {r.daily.map((d) => (
                  <Table.Tr key={d.date}>
                    <Table.Td>{f.longDate(d.date)}</Table.Td>
                    <Table.Td ta="right">{d.available}</Table.Td>
                    <Table.Td ta="right">{d.sold}</Table.Td>
                    <Table.Td ta="right">{f.pct(d.occupancy)}</Table.Td>
                    {fin && <Table.Td ta="right">{f.money(d.adr)}</Table.Td>}
                    {fin && <Table.Td ta="right">{f.money(d.revpar)}</Table.Td>}
                    {fin && <Table.Td ta="right">{f.money(d.revenue)}</Table.Td>}
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}
      </ChartCard>

      {fin && (
        <ChartCard title={t('reports.adr_by_night')} subtitle={t('reports.adr_hint')}>
          <LineChart labels={labels} titles={titles} series={adrSeries} format={(v) => f.money(v)} ariaLabel={t('reports.adr_by_night')} />
        </ChartCard>
      )}

      <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="lg">
        <ChartCard title={t('reports.by.source')} subtitle={t('reports.share_hint')}>
          <ShareTable
            rows={r.by_source.map((x) => ({ key: x.source, name: sourceName(x.source), ...x }))}
            fin={fin}
            f={f}
            testId="by-source"
          />
        </ChartCard>
        <ChartCard title={t('reports.by.room_type')}>
          <Table verticalSpacing={6} className="hms-num" data-testid="by-room-type">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t('reports.by.room_type')}</Table.Th>
                <Table.Th w="34%">{t('reports.occupancy')}</Table.Th>
                <Table.Th ta="right">{t('reports.sold')}</Table.Th>
                {fin && <Table.Th ta="right">{t('reports.adr')}</Table.Th>}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {r.by_room_type.map((x) => (
                <Table.Tr key={x.room_type_id}>
                  <Table.Td>{typeName(x.room_type_id)}</Table.Td>
                  <Table.Td>
                    <Group gap={8} wrap="nowrap">
                      <Box style={{ flex: 1 }}>
                        <Meter value={x.occupancy === null ? null : Number(x.occupancy)} label={`${typeName(x.room_type_id)} ${f.pct(x.occupancy)}`} />
                      </Box>
                      <Text size="sm" w={58} ta="right">
                        {f.pct(x.occupancy)}
                      </Text>
                    </Group>
                  </Table.Td>
                  <Table.Td ta="right">
                    {x.sold} / {x.available}
                  </Table.Td>
                  {fin && <Table.Td ta="right">{f.money(x.adr)}</Table.Td>}
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </ChartCard>
        <ChartCard title={t('reports.by.rate_plan')}>
          <ShareTable rows={r.by_rate_plan.map((x) => ({ key: x.rate_plan_id ?? 'none', name: planName(x.rate_plan_id), ...x }))} fin={fin} f={f} />
        </ChartCard>
        <ChartCard title={t('reports.bookings')} subtitle={t('reports.bookings_hint')}>
          <Table verticalSpacing={6} className="hms-num">
            <Table.Tbody>
              {[
                [t('reports.created'), f.num(r.bookings.created)],
                [t('reports.cancellation_rate'), `${f.pct(r.bookings.cancellation_rate)} (${r.bookings.cancelled})`],
                [t('reports.arrivals'), f.num(r.bookings.arrivals)],
                [t('reports.no_show_rate'), `${f.pct(r.bookings.no_show_rate)} (${r.bookings.no_shows})`],
                [t('reports.average_stay'), r.bookings.average_stay === null ? '—' : t('reports.nights_n', { count: Number(r.bookings.average_stay), value: f.num(r.bookings.average_stay, 1) })],
                [t('reports.lead_time'), r.bookings.average_lead_days === null ? '—' : t('reports.days_n', { count: Number(r.bookings.average_lead_days), value: f.num(r.bookings.average_lead_days, 1) })],
              ].map(([k, v]) => (
                <Table.Tr key={k}>
                  <Table.Td>{k}</Table.Td>
                  <Table.Td ta="right" fw={600}>
                    {v}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </ChartCard>
      </SimpleGrid>

      {fin && other && (
        <ChartCard title={t('reports.revenue_by_department')} subtitle={t('reports.revenue_hint')}>
          <Table verticalSpacing={6} className="hms-num" data-testid="revenue-table">
            <Table.Tbody>
              {(
                [
                  ['rooms', roomRevenue, r.totals.sold],
                  ['restaurant', other.restaurant, other.restaurant_checks],
                  ['vehicles', other.vehicles, other.rentals],
                  ['services', other.services, null],
                  ['fees', other.fees, null],
                  ['adjustments', other.adjustments, null],
                ] as [string, string | number, number | null][]
              ).map(([k, v, n]) => (
                <Table.Tr key={k}>
                  <Table.Td>
                    {t(`reports.departments.${k}`)}
                    {n !== null && (
                      <Text span size="xs" c="dimmed">
                        {' '}
                        · {t(`reports.departments.${k}_count`, { count: n })}
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td ta="right">{f.money(v)}</Table.Td>
                </Table.Tr>
              ))}
              <Table.Tr>
                <Table.Td fw={700}>{t('reports.total_revenue')}</Table.Td>
                <Table.Td ta="right" fw={700}>
                  {f.money(roomRevenue + Number(other.total))}
                </Table.Td>
              </Table.Tr>
            </Table.Tbody>
          </Table>
        </ChartCard>
      )}
    </Stack>
  );
}

function addDaysIso(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

/** Ranked horizontal bars (share of room nights), with the figures beside them. */
function ShareTable({
  rows,
  fin,
  f,
  testId,
}: {
  rows: { key: string; name: string; sold: number; share: string | null; revenue: string | null; adr: string | null }[];
  fin: boolean;
  f: ReturnType<typeof useFormatters>;
  testId?: string;
}) {
  const { t } = useTranslation();
  if (rows.length === 0)
    return (
      <Text size="sm" c="dimmed">
        {t('reports.nothing_sold')}
      </Text>
    );
  return (
    <Table verticalSpacing={6} className="hms-num" data-testid={testId}>
      <Table.Thead>
        <Table.Tr>
          <Table.Th />
          <Table.Th w="34%">{t('reports.share')}</Table.Th>
          <Table.Th ta="right">{t('reports.sold')}</Table.Th>
          {fin && <Table.Th ta="right">{t('reports.revenue')}</Table.Th>}
          {fin && <Table.Th ta="right">{t('reports.adr')}</Table.Th>}
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {rows.map((x) => (
          <Table.Tr key={x.key} data-row={x.key}>
            <Table.Td>{x.name}</Table.Td>
            <Table.Td>
              <Group gap={8} wrap="nowrap">
                <Box style={{ flex: 1 }}>
                  <Meter value={x.share === null ? null : Number(x.share)} label={`${x.name} ${f.pct(x.share)}`} />
                </Box>
                <Text size="sm" w={58} ta="right">
                  {f.pct(x.share)}
                </Text>
              </Group>
            </Table.Td>
            <Table.Td ta="right">{x.sold}</Table.Td>
            {fin && <Table.Td ta="right">{f.money(x.revenue)}</Table.Td>}
            {fin && <Table.Td ta="right">{f.money(x.adr)}</Table.Td>}
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}
