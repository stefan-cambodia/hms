import { useMemo, useState } from 'react';
import { Link } from 'react-router';
import {
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Drawer,
  Group,
  Modal,
  NumberInput,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Table,
  Tabs,
  Text,
  Textarea,
  TextInput,
  Title,
} from '@mantine/core';
import { useForm } from '@mantine/form';
import { IconBuildingBank, IconCash, IconEdit, IconPlus, IconSearch } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { api } from '@/api/client';
import { useHotelMutation, useHotelQuery } from '@/api/hooks';
import type { AgingBucket, CompanyAccount, CompanyAccountDetail, PaymentMethod } from '@/api/types';
import { useAuth, useHotel } from '@/auth/AuthProvider';
import { EmptyState, PageHeader, SubmitButton } from '@/components/ui';
import { LANGUAGES } from '@/i18n';
import { applyFieldErrors, errorMessage, notifyError, notifySuccess } from '@/lib/errors';
import { countryName, formatDate, formatDateTime, formatMoney } from '@/lib/format';
import { COUNTRY_CODES } from '@/lib/refdata';
import { PdfMenu } from '@/modules/billing/FolioSection';
import { PAYMENT_METHODS, toBase, usePaymentCurrencies } from '@/modules/billing/shared';

const ENTITIES = ['company_account', 'payment', 'night_audit'];
const AGING: AgingBucket[] = ['current', 'days_1_30', 'days_31_60', 'days_61_90', 'days_over_90'];

export default function AccountsPage() {
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const [q, setQ] = useState('');
  const [state, setState] = useState<'active' | 'all'>('active');
  const [openId, setOpenId] = useState<string | null>(null);
  const [editing, setEditing] = useState<Partial<CompanyAccount> | null>(null);
  const list = useHotelQuery<CompanyAccount[]>('company_account', '/company-accounts', { q: q.trim() || undefined, active: state === 'active' ? true : undefined });
  const money = (v: string, cur: string) => formatMoney(v, cur, i18n.language);
  const rows = list.data ?? [];

  return (
    <>
      <PageHeader
        title={t('nav.accounts')}
        description={t('accounts.description')}
        actions={
          can('accounts.manage') && (
            <Button leftSection={<IconPlus size={16} />} onClick={() => setEditing({})}>
              {t('accounts.add')}
            </Button>
          )
        }
      />
      <Group mb="md" gap="sm" wrap="wrap">
        <TextInput leftSection={<IconSearch size={16} />} placeholder={t('accounts.search')} value={q} onChange={(e) => setQ(e.currentTarget.value)} w={280} />
        <SegmentedControl
          value={state}
          onChange={(v) => setState(v as 'active' | 'all')}
          data={[
            { value: 'active', label: t('common.active') },
            { value: 'all', label: t('accounts.all') },
          ]}
        />
      </Group>
      {rows.length === 0 && !list.isPending ? (
        <EmptyState title={t('accounts.empty')} description={t('accounts.empty_hint')} />
      ) : (
        <Card p={0}>
          <div className="hms-table-wrap">
            <Table highlightOnHover miw={760} data-testid="accounts-table">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t('accounts.company')}</Table.Th>
                  <Table.Th>{t('accounts.contact')}</Table.Th>
                  <Table.Th>{t('accounts.terms')}</Table.Th>
                  <Table.Th ta="right">{t('accounts.balance')}</Table.Th>
                  <Table.Th ta="right">{t('accounts.overdue')}</Table.Th>
                  <Table.Th>{t('common.status')}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {rows.map((a) => (
                  <Table.Tr key={a.id} style={{ cursor: 'pointer' }} onClick={() => setOpenId(a.id)} data-account={a.code}>
                    <Table.Td>
                      <Text fw={600} size="sm">
                        {a.name}
                      </Text>
                      <Text size="xs" c="dimmed">
                        {a.code}
                        {a.tax_id ? ` · ${a.tax_id}` : ''}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm">{a.contact_name ?? '—'}</Text>
                      <Text size="xs" c="dimmed">
                        {a.email ?? ''}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm">{t('accounts.terms_days', { n: a.payment_terms_days })}</Text>
                      {a.credit_limit && (
                        <Text size="xs" c="dimmed">
                          {t('accounts.limit_short', { amount: money(a.credit_limit, a.currency) })}
                        </Text>
                      )}
                    </Table.Td>
                    <Table.Td ta="right" className="hms-num">
                      <Text size="sm" fw={600} c={Number(a.balance) > 0 ? undefined : Number(a.balance) < 0 ? 'orange.7' : 'dimmed'}>
                        {money(a.balance, a.currency)}
                      </Text>
                      <Text size="xs" c="dimmed">
                        {t('accounts.open_invoices', { n: a.open_items })}
                      </Text>
                    </Table.Td>
                    <Table.Td ta="right" className="hms-num">
                      <Text size="sm" c={Number(a.overdue) > 0 ? 'red.7' : 'dimmed'} fw={Number(a.overdue) > 0 ? 600 : 400}>
                        {money(a.overdue, a.currency)}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Badge variant="light" color={a.is_active ? 'lagoon' : 'gray'} radius="sm">
                        {a.is_active ? t('common.active') : t('common.inactive')}
                      </Badge>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </div>
        </Card>
      )}
      {openId && <AccountDetailDrawer id={openId} onClose={() => setOpenId(null)} onEdit={(a) => setEditing(a)} />}
      {editing && <AccountFormDrawer account={editing} onClose={() => setEditing(null)} onSaved={(id) => setOpenId(id)} />}
    </>
  );
}

function AccountDetailDrawer({ id, onClose, onEdit }: { id: string; onClose: () => void; onEdit: (a: CompanyAccount) => void }) {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const { can } = useAuth();
  const detail = useHotelQuery<CompanyAccountDetail>('company_account', `/company-accounts/${id}`);
  const [paying, setPaying] = useState(false);
  const [voiding, setVoiding] = useState<string | null>(null);
  const a = detail.data;
  const money = (v: string) => formatMoney(v, a?.currency ?? hotel.currency_code, i18n.language);
  const open = (a?.items ?? []).filter((i) => Number(i.open) > 0);

  return (
    <Drawer opened onClose={onClose} position="right" size="xl" title={<Title order={3}>{a?.name ?? ''}</Title>}>
      {a && (
        <Stack data-testid="account-detail">
          <Group justify="space-between" align="flex-start" wrap="wrap">
            <div>
              <Text size="xs" c="dimmed">
                {t('accounts.balance')}
              </Text>
              <Text fw={700} fz={26} c={Number(a.balance) < 0 ? 'orange.7' : undefined} data-testid="account-balance">
                {money(a.balance)}
              </Text>
              {Number(a.overdue) > 0 && (
                <Text size="sm" c="red.7" fw={600}>
                  {t('accounts.overdue_amount', { amount: money(a.overdue) })}
                </Text>
              )}
            </div>
            <Group gap="xs">
              {can('payments.record') && (
                <Button leftSection={<IconCash size={16} />} onClick={() => setPaying(true)}>
                  {t('accounts.record_payment')}
                </Button>
              )}
              <PdfMenu path={`/company-accounts/${a.id}/statement.pdf`} label={t('accounts.statement')} />
              {can('accounts.manage') && (
                <Button variant="default" leftSection={<IconEdit size={16} />} onClick={() => onEdit(a)}>
                  {t('common.edit')}
                </Button>
              )}
            </Group>
          </Group>
          <SimpleGrid cols={{ base: 2, sm: 5 }} spacing="xs" data-testid="account-aging">
            {AGING.map((k) => (
              <Card key={k} withBorder padding="xs">
                <Text size="xs" c="dimmed">
                  {t(`accounts.aging.${k}`)}
                </Text>
                <Text size="sm" fw={600} c={k !== 'current' && Number(a.aging[k]) > 0 ? 'red.7' : undefined}>
                  {money(a.aging[k])}
                </Text>
              </Card>
            ))}
          </SimpleGrid>

          <Tabs defaultValue="invoices">
            <Tabs.List>
              <Tabs.Tab value="invoices">{t('accounts.invoices_tab', { n: open.length })}</Tabs.Tab>
              <Tabs.Tab value="payments">{t('accounts.payments_tab')}</Tabs.Tab>
              <Tabs.Tab value="details">{t('accounts.details_tab')}</Tabs.Tab>
            </Tabs.List>
            <Tabs.Panel value="invoices" pt="sm">
              {a.items.length === 0 ? (
                <Text size="sm" c="dimmed">
                  {t('accounts.no_invoices')}
                </Text>
              ) : (
                <div className="hms-table-wrap">
                  <Table miw={620} data-testid="account-items">
                    <Table.Thead>
                      <Table.Tr>
                        <Table.Th>{t('accounts.invoice')}</Table.Th>
                        <Table.Th>{t('accounts.due')}</Table.Th>
                        <Table.Th ta="right">{t('accounts.amount')}</Table.Th>
                        <Table.Th ta="right">{t('accounts.open')}</Table.Th>
                      </Table.Tr>
                    </Table.Thead>
                    <Table.Tbody>
                      {a.items.map((i) => (
                        <Table.Tr key={i.transfer_id} c={i.is_void ? 'dimmed' : undefined} td={i.is_void ? 'line-through' : undefined}>
                          <Table.Td>
                            <Text size="sm" fw={600}>
                              {i.invoice_number}
                            </Text>
                            <Text size="xs" c="dimmed">
                              <Anchor component={Link} to={`/reservations/${i.reservation_id}`} size="xs">
                                {i.reservation_code}
                              </Anchor>{' '}
                              · {i.guest_name} · {formatDate(i.date, i18n.language)}
                            </Text>
                          </Table.Td>
                          <Table.Td>
                            <Text size="sm">{formatDate(i.due_date, i18n.language)}</Text>
                            {i.days_overdue > 0 && (
                              <Badge color="red" variant="light" size="sm">
                                {t('accounts.days_late', { n: i.days_overdue })}
                              </Badge>
                            )}
                          </Table.Td>
                          <Table.Td ta="right" className="hms-num">
                            {money(i.amount)}
                          </Table.Td>
                          <Table.Td ta="right" className="hms-num">
                            <Text size="sm" fw={600} c={Number(i.open) > 0 ? undefined : 'teal.7'}>
                              {Number(i.open) > 0 ? money(i.open) : t('accounts.settled')}
                            </Text>
                          </Table.Td>
                        </Table.Tr>
                      ))}
                    </Table.Tbody>
                  </Table>
                </div>
              )}
            </Tabs.Panel>
            <Tabs.Panel value="payments" pt="sm">
              {a.payments.length === 0 ? (
                <Text size="sm" c="dimmed">
                  {t('accounts.no_payments')}
                </Text>
              ) : (
                <Stack gap="xs" data-testid="account-payments">
                  {a.payments.map((p) => (
                    <Card key={p.id} withBorder padding="sm" opacity={p.is_void ? 0.6 : 1}>
                      <Group justify="space-between" wrap="nowrap" align="flex-start">
                        <div>
                          <Text size="sm" fw={600} td={p.is_void ? 'line-through' : undefined}>
                            {p.number} · {t(`billing.methods.${p.method}`)} · {formatMoney(p.amount, p.currency, i18n.language)}
                          </Text>
                          <Text size="xs" c="dimmed">
                            {formatDateTime(p.received_at, i18n.language, hotel.timezone)}
                            {p.received_by_name ? ` · ${p.received_by_name}` : ''}
                            {p.reference ? ` · ${p.reference}` : ''}
                          </Text>
                          {!p.is_void && (
                            <Text size="xs">
                              {p.allocations.map((x) => `${x.invoice_number} ${money(x.amount)}`).join(' · ')}
                              {Number(p.unallocated) > 0 ? ` · ${t('accounts.unallocated', { amount: money(p.unallocated) })}` : ''}
                            </Text>
                          )}
                          {p.is_void && (
                            <Text size="xs" c="red.7">
                              {t('accounts.voided_reason', { reason: p.void_reason })}
                            </Text>
                          )}
                        </div>
                        {!p.is_void && can('payments.void') && (
                          <Button size="xs" variant="subtle" color="red" onClick={() => setVoiding(p.id)}>
                            {t('billing.void')}
                          </Button>
                        )}
                      </Group>
                    </Card>
                  ))}
                </Stack>
              )}
            </Tabs.Panel>
            <Tabs.Panel value="details" pt="sm">
              <AccountDetails account={a} />
            </Tabs.Panel>
          </Tabs>
        </Stack>
      )}
      {a && paying && <AccountPaymentModal account={a} onClose={() => setPaying(false)} />}
      {a && voiding && <VoidAccountPaymentModal accountId={a.id} paymentId={voiding} onClose={() => setVoiding(null)} />}
    </Drawer>
  );
}

function AccountDetails({ account: a }: { account: CompanyAccount }) {
  const { t, i18n } = useTranslation();
  const rows: [string, string | null][] = [
    [t('accounts.code'), a.code],
    [t('accounts.legal_name'), a.legal_name],
    [t('accounts.tax_id'), a.tax_id],
    [t('accounts.address'), [a.address, a.city, a.country_code && countryName(a.country_code, i18n.language)].filter(Boolean).join(', ') || null],
    [t('accounts.contact'), [a.contact_name, a.email, a.phone].filter(Boolean).join(' · ') || null],
    [t('accounts.language'), LANGUAGES.find((l) => l.code === a.language)?.label ?? null],
    [t('accounts.terms'), t('accounts.terms_days', { n: a.payment_terms_days })],
    [t('accounts.credit_limit'), a.credit_limit ? formatMoney(a.credit_limit, a.currency, i18n.language) : t('accounts.no_limit')],
    [t('accounts.notes'), a.notes],
  ];
  return (
    <Table>
      <Table.Tbody>
        {rows.map(([label, value]) => (
          <Table.Tr key={label}>
            <Table.Td c="dimmed" w="35%">
              {label}
            </Table.Td>
            <Table.Td style={{ whiteSpace: 'pre-wrap' }}>{value || '—'}</Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}

type FormValues = {
  code: string;
  name: string;
  legal_name: string;
  tax_id: string;
  address: string;
  city: string;
  country_code: string | null;
  email: string;
  phone: string;
  contact_name: string;
  language: string | null;
  payment_terms_days: number | string;
  credit_limit: number | string;
  is_active: boolean;
  notes: string;
};

function AccountFormDrawer({ account, onClose, onSaved }: { account: Partial<CompanyAccount>; onClose: () => void; onSaved: (id: string) => void }) {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const form = useForm<FormValues>({
    initialValues: {
      code: account.code ?? '',
      name: account.name ?? '',
      legal_name: account.legal_name ?? '',
      tax_id: account.tax_id ?? '',
      address: account.address ?? '',
      city: account.city ?? '',
      country_code: account.country_code ?? null,
      email: account.email ?? '',
      phone: account.phone ?? '',
      contact_name: account.contact_name ?? '',
      language: account.language ?? null,
      payment_terms_days: account.payment_terms_days ?? 30,
      credit_limit: account.credit_limit ?? '',
      is_active: account.is_active ?? true,
      notes: account.notes ?? '',
    },
  });
  const countries = useMemo(
    () => COUNTRY_CODES.map((c) => ({ value: c, label: countryName(c, i18n.language) })).sort((x, y) => x.label.localeCompare(y.label, i18n.language)),
    [i18n.language],
  );
  const save = useHotelMutation<Record<string, unknown>, CompanyAccountDetail>(
    (h, body) => (account.id ? api.patch(h(`/company-accounts/${account.id}`), body) : api.post(h('/company-accounts'), body)),
    ENTITIES,
  );
  const blank = (v: string) => v.trim() || null;
  const submit = form.onSubmit(async (v) => {
    const body: Record<string, unknown> = {
      name: v.name.trim(),
      legal_name: blank(v.legal_name),
      tax_id: blank(v.tax_id),
      address: blank(v.address),
      city: blank(v.city),
      country_code: v.country_code,
      email: blank(v.email),
      phone: blank(v.phone),
      contact_name: blank(v.contact_name),
      language: v.language,
      payment_terms_days: Number(v.payment_terms_days),
      credit_limit: v.credit_limit === '' ? null : String(v.credit_limit),
      is_active: v.is_active,
      notes: blank(v.notes),
    };
    if (account.id) body.version = account.version;
    else body.code = v.code.trim();
    try {
      const saved = await save.mutateAsync(body);
      notifySuccess(t('common.saved'));
      onClose();
      onSaved(saved.id);
    } catch (err) {
      if (!applyFieldErrors(err, form.setFieldError)) notifyError(err);
    }
  });

  return (
    <Drawer opened onClose={onClose} position="right" size="lg" title={account.id ? t('accounts.edit') : t('accounts.add')}>
      <form onSubmit={submit}>
        <Stack>
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <TextInput label={t('accounts.code')} description={t('common.code_hint')} required disabled={!!account.id} {...form.getInputProps('code')} />
            <TextInput label={t('accounts.name')} required {...form.getInputProps('name')} />
            <TextInput label={t('accounts.legal_name')} {...form.getInputProps('legal_name')} />
            <TextInput label={t('accounts.tax_id')} {...form.getInputProps('tax_id')} />
          </SimpleGrid>
          <TextInput label={t('accounts.address')} {...form.getInputProps('address')} />
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <TextInput label={t('accounts.city')} {...form.getInputProps('city')} />
            <Select label={t('accounts.country')} data={countries} searchable clearable {...form.getInputProps('country_code')} />
            <TextInput label={t('accounts.contact_name')} {...form.getInputProps('contact_name')} />
            <TextInput label={t('accounts.email')} type="email" {...form.getInputProps('email')} />
            <TextInput label={t('accounts.phone')} type="tel" {...form.getInputProps('phone')} />
            <Select
              label={t('accounts.language')}
              description={t('accounts.language_hint')}
              data={LANGUAGES.map((l) => ({ value: l.code, label: l.label }))}
              clearable
              {...form.getInputProps('language')}
            />
            <NumberInput label={t('accounts.terms')} description={t('accounts.terms_hint')} min={0} max={365} allowDecimal={false} suffix={` ${t('accounts.days')}`} {...form.getInputProps('payment_terms_days')} />
            <NumberInput label={t('accounts.credit_limit')} description={`${hotel.currency_code} · ${t('accounts.credit_limit_hint')}`} min={0} decimalScale={2} {...form.getInputProps('credit_limit')} />
          </SimpleGrid>
          <Textarea label={t('accounts.notes')} autosize minRows={2} {...form.getInputProps('notes')} />
          <Switch label={t('accounts.active_hint')} {...form.getInputProps('is_active', { type: 'checkbox' })} />
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <SubmitButton loading={save.isPending}>{t('common.save')}</SubmitButton>
          </Group>
        </Stack>
      </form>
    </Drawer>
  );
}

function AccountPaymentModal({ account: a, onClose }: { account: CompanyAccountDetail; onClose: () => void }) {
  const { t, i18n } = useTranslation();
  const currencies = usePaymentCurrencies();
  const [method, setMethod] = useState<PaymentMethod>('bank_transfer');
  const [currency, setCurrency] = useState(a.currency);
  const [amount, setAmount] = useState<number | string>(Number(a.balance) > 0 ? Number(a.balance) : '');
  const [reference, setReference] = useState('');
  const [notes, setNotes] = useState('');
  const [error, setError] = useState<string | null>(null);
  const rate = currencies.rate(currency);
  const base = toBase(Number(amount), rate);
  const save = useHotelMutation<Record<string, unknown>, CompanyAccountDetail>((h, body) => api.post(h(`/company-accounts/${a.id}/payments`), body), ENTITIES);
  const submit = () => {
    setError(null);
    void save
      .mutateAsync({
        method,
        amount: String(amount),
        currency,
        exchange_rate: currency === a.currency ? undefined : rate,
        reference: reference.trim() || undefined,
        notes: notes.trim() || undefined,
      })
      .then(
        () => {
          notifySuccess(t('accounts.payment_recorded'));
          onClose();
        },
        (err) => setError(errorMessage(err)),
      );
  };
  return (
    <Modal opened onClose={onClose} title={t('accounts.record_payment_for', { name: a.name })} size="md">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (Number(amount) > 0) submit();
        }}
      >
        <Stack>
          {error && <Alert color="red">{error}</Alert>}
          <Text size="sm" c="dimmed">
            {t('accounts.payment_hint')}
          </Text>
          <Select label={t('billing.method')} allowDeselect={false} data={PAYMENT_METHODS.map((m) => ({ value: m, label: t(`billing.methods.${m}`) }))} value={method} onChange={(v) => v && setMethod(v as PaymentMethod)} />
          <SimpleGrid cols={2}>
            <NumberInput label={t('accounts.amount')} min={0} decimalScale={2} required value={amount} onChange={setAmount} data-autofocus />
            <Select label={t('billing.currency')} allowDeselect={false} data={currencies.list} value={currency} onChange={(v) => v && setCurrency(v)} />
          </SimpleGrid>
          {currency !== a.currency && base !== null && (
            <Text size="xs" c="dimmed">
              {t('accounts.equivalent', { amount: formatMoney(base, a.currency, i18n.language) })}
            </Text>
          )}
          <TextInput label={t('accounts.reference')} placeholder={t('accounts.reference_placeholder')} maxLength={100} value={reference} onChange={(e) => setReference(e.currentTarget.value)} />
          <Textarea label={t('accounts.notes')} autosize minRows={1} maxLength={500} value={notes} onChange={(e) => setNotes(e.currentTarget.value)} />
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <SubmitButton loading={save.isPending} disabled={!(Number(amount) > 0)} leftSection={<IconBuildingBank size={16} />}>
              {t('accounts.record_payment')}
            </SubmitButton>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

function VoidAccountPaymentModal({ accountId, paymentId, onClose }: { accountId: string; paymentId: string; onClose: () => void }) {
  const { t } = useTranslation();
  const [reason, setReason] = useState('');
  const save = useHotelMutation<string, CompanyAccountDetail>((h, why) => api.post(h(`/company-accounts/${accountId}/payments/${paymentId}/void`), { reason: why }), ENTITIES);
  return (
    <Modal opened onClose={onClose} title={t('accounts.void_payment')}>
      <Stack>
        <Text size="sm">{t('accounts.void_payment_hint')}</Text>
        <TextInput label={t('accounts.void_reason')} required value={reason} onChange={(e) => setReason(e.currentTarget.value)} data-autofocus />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            color="red"
            disabled={!reason.trim()}
            loading={save.isPending}
            onClick={() =>
              void save.mutateAsync(reason.trim()).then(() => {
                notifySuccess(t('accounts.payment_voided'));
                onClose();
              }, notifyError)
            }
          >
            {t('billing.void')}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
