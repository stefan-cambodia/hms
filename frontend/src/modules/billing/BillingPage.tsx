import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { Anchor, Badge, Button, Card, Group, Pagination, Select, SimpleGrid, Stack, Switch, Table, Tabs, Text, TextInput } from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import { useDebouncedValue } from '@mantine/hooks';
import { IconFileInvoice, IconReceipt, IconSearch } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { api } from '@/api/client';
import { useHotelMutation, useHotelQuery } from '@/api/hooks';
import type { Invoice, InvoiceListItem, Page, PaymentReport } from '@/api/types';
import { useAuth, useHotel } from '@/auth/AuthProvider';
import { EmptyState, PageHeader } from '@/components/ui';
import { formatDate, formatDateTime, formatMoney, formatNumber } from '@/lib/format';
import { useHotelToday } from '@/modules/reservations/shared';
import { ReasonModal } from './FolioDialogs';
import { PAYMENT_METHODS, usePaymentCurrencies, useDocumentUrl } from './shared';

const PAGE = 50;

export default function BillingPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const params = useParams();
  const navigate = useNavigate();
  const tabs = [can('payments.view') && 'payments', can('invoices.view') && 'invoices'].filter(Boolean) as string[];
  const active = tabs.includes(params['*'] ?? '') ? params['*']! : tabs[0];
  return (
    <>
      <PageHeader title={t('nav.billing')} description={t('billing.page_description')} />
      <Tabs value={active} onChange={(v) => v && navigate(`/billing/${v}`)} keepMounted={false}>
        <Tabs.List mb="md">
          {tabs.includes('payments') && (
            <Tabs.Tab value="payments" leftSection={<IconReceipt size={16} />}>
              {t('billing.payments')}
            </Tabs.Tab>
          )}
          {tabs.includes('invoices') && (
            <Tabs.Tab value="invoices" leftSection={<IconFileInvoice size={16} />}>
              {t('billing.invoices')}
            </Tabs.Tab>
          )}
        </Tabs.List>
        <Tabs.Panel value="payments">
          <PaymentsTab />
        </Tabs.Panel>
        <Tabs.Panel value="invoices">
          <InvoicesTab />
        </Tabs.Panel>
      </Tabs>
    </>
  );
}

/** Payments over a period with totals per method and currency (cash-up report). */
function PaymentsTab() {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const today = useHotelToday();
  const currencies = usePaymentCurrencies();
  const url = useDocumentUrl();
  const [range, setRange] = useState<[string | null, string | null]>([today, today]);
  const [method, setMethod] = useState<string | null>(null);
  const [currency, setCurrency] = useState<string | null>(null);
  const [withVoid, setWithVoid] = useState(false);
  const [page, setPage] = useState(1);
  const report = useHotelQuery<PaymentReport>('payment', '/payments', {
    start: range[0],
    end: range[1] ?? range[0],
    method,
    currency,
    include_void: withVoid || undefined,
    limit: PAGE,
    offset: (page - 1) * PAGE,
  });
  const data = report.data;
  return (
    <Stack>
      <Card padding="sm">
        <Group gap="sm" wrap="wrap">
          <DatePickerInput type="range" value={range} onChange={(v) => { setRange([v[0], v[1]]); setPage(1); }} valueFormat="D MMM YYYY" w={260} aria-label={t('billing.period')} allowSingleDateInRange />
          <Select placeholder={t('billing.method')} clearable data={PAYMENT_METHODS.map((m) => ({ value: m, label: t(`billing.methods.${m}`) }))} value={method} onChange={(v) => { setMethod(v); setPage(1); }} w={180} />
          <Select placeholder={t('billing.currency')} clearable data={currencies.list} value={currency} onChange={(v) => { setCurrency(v); setPage(1); }} w={120} />
          <Switch label={t('billing.show_voided')} checked={withVoid} onChange={(e) => setWithVoid(e.currentTarget.checked)} />
        </Group>
      </Card>
      {data && data.summary.length > 0 && (
        <Card padding="sm" data-testid="payment-summary">
          <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }} spacing="xs">
            {data.summary.map((s) => (
              <Group key={`${s.method}-${s.currency}-${s.kind}`} justify="space-between" wrap="nowrap">
                <Text size="sm">
                  {t(`billing.methods.${s.method}`)} · {s.currency}
                  {s.kind !== 'payment' ? ` · ${t(`billing.payment_kinds.${s.kind}`)}` : ''} <Text span c="dimmed" size="xs">({s.count})</Text>
                </Text>
                <Text size="sm" fw={600} className="hms-num" c={s.kind === 'refund' ? 'orange.7' : undefined}>
                  {s.kind === 'refund' ? '−' : ''}
                  {formatMoney(s.amount, s.currency, i18n.language)}
                </Text>
              </Group>
            ))}
          </SimpleGrid>
          <Group justify="flex-end" mt="xs">
            <Text fw={700}>
              {t('billing.net_received')}: <span className="hms-num">{formatMoney(data.net_base, hotel.currency_code, i18n.language)}</span>
            </Text>
          </Group>
        </Card>
      )}
      {data && data.items.length === 0 ? (
        <EmptyState title={t('billing.no_payments_period')} />
      ) : (
        <Card padding={0}>
          <div className="hms-table-wrap">
            <Table miw={720} verticalSpacing="xs" highlightOnHover>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t('billing.received')}</Table.Th>
                  <Table.Th>{t('billing.number')}</Table.Th>
                  <Table.Th>{t('reservations.guest')}</Table.Th>
                  <Table.Th>{t('billing.method')}</Table.Th>
                  <Table.Th ta="right">{t('billing.amount')}</Table.Th>
                  <Table.Th w={60} />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {data?.items.map((p) => (
                  <Table.Tr key={p.id} style={p.is_void ? { opacity: 0.5 } : undefined}>
                    <Table.Td>
                      <Text size="sm">{formatDateTime(p.received_at, i18n.language, hotel.timezone)}</Text>
                      <Text size="xs" c="dimmed">
                        {p.received_by_name ?? '—'}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm" td={p.is_void ? 'line-through' : undefined}>
                        {p.number}
                      </Text>
                      {p.is_void && (
                        <Badge size="xs" color="red" variant="light">
                          {t('billing.void_status')}
                        </Badge>
                      )}
                    </Table.Td>
                    <Table.Td>
                      <Anchor component={Link} to={`/reservations/${p.reservation_id}`} size="sm">
                        {p.guest_name}
                      </Anchor>
                      <Text size="xs" c="dimmed">
                        {p.reservation_code}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm">
                        {t(`billing.payment_kinds.${p.kind}`)} · {t(`billing.methods.${p.method}`)}
                        {p.card_last4 ? ` ···· ${p.card_last4}` : ''}
                      </Text>
                      {p.reference && (
                        <Text size="xs" c="dimmed">
                          {p.reference}
                        </Text>
                      )}
                    </Table.Td>
                    <Table.Td ta="right" className="hms-num">
                      <Text size="sm" fw={600} c={p.kind === 'refund' ? 'orange.7' : undefined}>
                        {p.kind === 'refund' ? '−' : ''}
                        {formatMoney(p.amount, p.currency, i18n.language)}
                      </Text>
                      {p.currency !== hotel.currency_code && (
                        <Text size="xs" c="dimmed">
                          = {formatMoney(p.amount_base, hotel.currency_code, i18n.language)} @ {formatNumber(p.exchange_rate, i18n.language, 6)}
                        </Text>
                      )}
                    </Table.Td>
                    <Table.Td>
                      <Button component="a" href={url(`/reservations/${p.reservation_id}/payments/${p.id}/receipt.pdf`)} target="_blank" rel="noopener" size="xs" variant="subtle">
                        PDF
                      </Button>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </div>
        </Card>
      )}
      {data && data.total > PAGE && <Pagination total={Math.ceil(data.total / PAGE)} value={page} onChange={setPage} />}
    </Stack>
  );
}

function InvoicesTab() {
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const url = useDocumentUrl();
  const [search, setSearch] = useState('');
  const [q] = useDebouncedValue(search, 250);
  const [status, setStatus] = useState<string | null>(null);
  const [range, setRange] = useState<[string | null, string | null]>([null, null]);
  const [page, setPage] = useState(1);
  const [voiding, setVoiding] = useState<InvoiceListItem | null>(null);
  const list = useHotelQuery<Page<InvoiceListItem>>('invoice', '/invoices', {
    q,
    status,
    start: range[0],
    end: range[1],
    limit: PAGE,
    offset: (page - 1) * PAGE,
  });
  const voidInvoice = useHotelMutation<{ id: string; reason: string }, Invoice>(
    (h, { id, reason }) => api.post<Invoice>(h(`/invoices/${id}/void`), { reason }),
    ['invoice', 'folio', 'reservation'],
  );
  return (
    <Stack>
      <Card padding="sm">
        <Group gap="sm" wrap="wrap">
          <TextInput leftSection={<IconSearch size={16} />} placeholder={t('billing.invoice_search')} value={search} onChange={(e) => { setSearch(e.currentTarget.value); setPage(1); }} w={280} />
          <Select
            placeholder={t('common.status')}
            clearable
            data={[
              { value: 'issued', label: t('billing.issued_status') },
              { value: 'void', label: t('billing.void_status') },
            ]}
            value={status}
            onChange={(v) => { setStatus(v); setPage(1); }}
            w={160}
          />
          <DatePickerInput type="range" clearable placeholder={t('billing.period')} value={range} onChange={(v) => { setRange([v[0], v[1]]); setPage(1); }} valueFormat="D MMM YYYY" w={260} allowSingleDateInRange />
        </Group>
      </Card>
      {list.data && list.data.items.length === 0 ? (
        <EmptyState title={t('billing.no_invoices')} description={t('billing.no_invoices_hint')} />
      ) : (
        <Card padding={0}>
          <div className="hms-table-wrap">
            <Table miw={720} verticalSpacing="xs" highlightOnHover>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t('billing.number')}</Table.Th>
                  <Table.Th>{t('billing.issue_date')}</Table.Th>
                  <Table.Th>{t('billing.bill_to')}</Table.Th>
                  <Table.Th ta="right">{t('reservations.total')}</Table.Th>
                  <Table.Th ta="right">{t('reservations.balance')}</Table.Th>
                  <Table.Th w={140} />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {list.data?.items.map((x) => (
                  <Table.Tr key={x.id} style={x.status === 'void' ? { opacity: 0.55 } : undefined} data-invoice-row={x.number}>
                    <Table.Td>
                      <Group gap={6}>
                        <Text size="sm" fw={600} td={x.status === 'void' ? 'line-through' : undefined}>
                          {x.number}
                        </Text>
                        {x.status === 'void' && (
                          <Badge size="xs" color="red" variant="light">
                            {t('billing.void_status')}
                          </Badge>
                        )}
                      </Group>
                      <Anchor component={Link} to={`/reservations/${x.reservation_id}`} size="xs">
                        {x.reservation_code}
                      </Anchor>
                    </Table.Td>
                    <Table.Td>{formatDate(x.issue_date, i18n.language)}</Table.Td>
                    <Table.Td>
                      <Text size="sm">{x.bill_to.company || x.bill_to.name}</Text>
                      {x.bill_to.company && (
                        <Text size="xs" c="dimmed">
                          {x.bill_to.name}
                        </Text>
                      )}
                    </Table.Td>
                    <Table.Td ta="right" className="hms-num">
                      {formatMoney(x.total, x.currency, i18n.language)}
                    </Table.Td>
                    <Table.Td ta="right" className="hms-num">
                      {formatMoney(x.balance, x.currency, i18n.language)}
                    </Table.Td>
                    <Table.Td>
                      <Group gap={4} justify="flex-end" wrap="nowrap">
                        <Button component="a" href={url(`/invoices/${x.id}/pdf`)} target="_blank" rel="noopener" size="xs" variant="subtle">
                          PDF
                        </Button>
                        {x.status === 'issued' && can('invoices.void') && (
                          <Button size="xs" variant="subtle" color="red" onClick={() => setVoiding(x)}>
                            {t('billing.void')}
                          </Button>
                        )}
                      </Group>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </div>
        </Card>
      )}
      {list.data && list.data.total > PAGE && <Pagination total={Math.ceil(list.data.total / PAGE)} value={page} onChange={setPage} />}
      {voiding && (
        <ReasonModal
          title={t('billing.void_invoice', { number: voiding.number })}
          body={t('billing.void_invoice_body')}
          confirm={t('billing.void')}
          loading={voidInvoice.isPending}
          onClose={() => setVoiding(null)}
          onConfirm={(reason) => voidInvoice.mutateAsync({ id: voiding.id, reason })}
        />
      )}
    </Stack>
  );
}
