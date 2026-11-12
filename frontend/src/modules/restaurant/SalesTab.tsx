import { useState } from 'react';
import { Card, Group, Loader, SimpleGrid, Stack, Switch, Table, Text, Title } from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import { useTranslation } from 'react-i18next';

import { useHotelQuery } from '@/api/hooks';
import type { SalesReport } from '@/api/types';
import { useHotel } from '@/auth/AuthProvider';
import { formatMoney } from '@/lib/format';
import { useHotelToday } from '@/modules/reservations/shared';
import { useLocalized } from './shared';

export default function SalesTab({ outletId }: { outletId: string | null }) {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const loc = useLocalized();
  const today = useHotelToday();
  const [range, setRange] = useState<[string | null, string | null]>([today, today]);
  const [all, setAll] = useState(false);
  const report = useHotelQuery<SalesReport>('restaurant_order', '/restaurant/sales', {
    start: range[0],
    end: range[1] ?? range[0],
    outlet_id: all ? undefined : outletId,
  }, !!range[0]);
  const money = (v: string | number) => formatMoney(v, hotel.currency_code, i18n.language);
  const r = report.data;
  return (
    <Stack>
      <Group gap="sm">
        <DatePickerInput type="range" value={range} onChange={(v) => setRange([v[0], v[1]])} allowSingleDateInRange valueFormat="D MMM YYYY" w={260} aria-label={t('billing.period')} />
        <Switch label={t('restaurant.all_outlets')} checked={all} onChange={(e) => setAll(e.currentTarget.checked)} />
      </Group>
      {!r ? (
        <Loader size="sm" />
      ) : (
        <>
          <SimpleGrid cols={{ base: 2, md: 4 }} data-testid="sales-stats">
            <Stat label={t('restaurant.sales_total')} value={money(r.total)} />
            <Stat label={t('restaurant.checks')} value={String(r.orders)} />
            <Stat label={t('restaurant.covers')} value={String(r.covers)} />
            <Stat label={t('restaurant.average_check')} value={money(r.average_check)} />
          </SimpleGrid>
          <Card padding="sm">
            <SimpleGrid cols={{ base: 2, md: 5 }}>
              <Mini label={t('restaurant.subtotal')} value={money(r.subtotal)} />
              <Mini label={t('restaurant.discount')} value={money(r.discounts)} />
              <Mini label={t('restaurant.service')} value={money(r.service_charge)} />
              <Mini label={t('restaurant.taxes')} value={money(r.taxes)} />
              <Mini label={t('restaurant.voided', { count: r.voided_lines })} value={money(r.voided_amount)} />
            </SimpleGrid>
          </Card>
          <SimpleGrid cols={{ base: 1, md: 3 }}>
            <Card padding="sm">
              <Title order={5} mb="xs">
                {t('restaurant.by_category')}
              </Title>
              <SmallTable rows={r.by_category.map((c) => [loc(c.name) || '—', String(c.quantity), money(c.amount)])} />
            </Card>
            <Card padding="sm">
              <Title order={5} mb="xs">
                {t('restaurant.top_items')}
              </Title>
              <SmallTable rows={r.top_items.map((i) => [loc(i.name), String(i.quantity), money(i.amount)])} />
            </Card>
            <Card padding="sm">
              <Title order={5} mb="xs">
                {t('restaurant.by_method')}
              </Title>
              <SmallTable
                rows={r.by_method.map((m) => [
                  `${m.method === 'room_charge' ? t('restaurant.room_charge') : t(`billing.methods.${m.method}`)} · ${m.currency}`,
                  String(m.count),
                  formatMoney(m.amount, m.currency, i18n.language),
                ])}
              />
            </Card>
          </SimpleGrid>
        </>
      )}
    </Stack>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <Card padding="sm">
      <Text size="xs" c="dimmed" fw={600}>
        {label}
      </Text>
      <Text size="xl" fw={700} className="hms-num">
        {value}
      </Text>
    </Card>
  );
}

function Mini({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      <Text fw={600} className="hms-num">
        {value}
      </Text>
    </div>
  );
}

function SmallTable({ rows }: { rows: string[][] }) {
  const { t } = useTranslation();
  if (rows.length === 0) return <Text size="sm" c="dimmed">{t('restaurant.no_sales')}</Text>;
  return (
    <Table verticalSpacing={4}>
      <Table.Tbody>
        {rows.map((r, i) => (
          <Table.Tr key={i}>
            <Table.Td>
              <Text size="sm">{r[0]}</Text>
            </Table.Td>
            <Table.Td ta="right" className="hms-num">
              <Text size="sm">{r[1]}</Text>
            </Table.Td>
            <Table.Td ta="right" className="hms-num">
              <Text size="sm">{r[2]}</Text>
            </Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}
