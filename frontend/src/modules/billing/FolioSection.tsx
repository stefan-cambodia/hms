import { useState, type ReactNode } from 'react';
import { ActionIcon, Alert, Badge, Button, Card, Divider, Group, Menu, Stack, Table, Text, Title, Tooltip } from '@mantine/core';
import { modals } from '@mantine/modals';
import { IconBuildingBank, IconCash, IconDotsVertical, IconFileInvoice, IconPlus, IconPrinter, IconReceipt, IconTrash } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { api } from '@/api/client';
import { useHotelMutation, useHotelQuery } from '@/api/hooks';
import type { Folio, Invoice, Reservation } from '@/api/types';
import { useAuth, useHotel } from '@/auth/AuthProvider';
import { LANGUAGES } from '@/i18n';
import { notifyError, notifySuccess } from '@/lib/errors';
import { formatDate, formatDateTime, formatMoney, formatNumber } from '@/lib/format';
import { useCompanyAccounts } from '@/modules/accounts/shared';
import { pickLocalized } from '@/lib/localized';
import { useInventory } from '@/modules/reservations/shared';
import { ChargeModal, InvoiceModal, PaymentModal, ReasonModal } from './FolioDialogs';
import { chargeTitle, useDocumentUrl } from './shared';

type Dialog =
  | { kind: 'charge' }
  | { kind: 'payment'; refund?: boolean }
  | { kind: 'invoice' }
  | { kind: 'void_charge'; id: string }
  | { kind: 'void_payment'; id: string }
  | { kind: 'void_invoice'; invoice: Invoice };

/** PDF link menu: the guest's language first, then every UI language. */
export function PdfMenu({ path, label, icon, fixedLanguage }: { path: string; label: string; icon?: ReactNode; fixedLanguage?: boolean }) {
  const { t } = useTranslation();
  const url = useDocumentUrl();
  if (fixedLanguage)
    return (
      <Button component="a" href={url(path)} target="_blank" rel="noopener" variant="default" size="xs" leftSection={icon ?? <IconPrinter size={14} />}>
        {label}
      </Button>
    );
  return (
    <Menu position="bottom-end" withinPortal>
      <Menu.Target>
        <Button variant="default" size="xs" leftSection={icon ?? <IconPrinter size={14} />}>
          {label}
        </Button>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Item component="a" href={url(path)} target="_blank" rel="noopener">
          {t('billing.guest_language')}
        </Menu.Item>
        <Menu.Divider />
        {LANGUAGES.map((l) => (
          <Menu.Item key={l.code} component="a" href={url(path, l.code)} target="_blank" rel="noopener">
            {l.label}
          </Menu.Item>
        ))}
      </Menu.Dropdown>
    </Menu>
  );
}

export function FolioSection({ reservation: r }: { reservation: Reservation }) {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const { can } = useAuth();
  const inv = useInventory();
  const url = useDocumentUrl();
  const folio = useHotelQuery<Folio>('folio', `/reservations/${r.id}/folio`);
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const voidCharge = useHotelMutation<{ id: string; reason: string }, Folio>(
    (h, { id, reason }) => api.post<Folio>(h(`/reservations/${r.id}/charges/${id}/void`), { reason }),
    ['folio', 'reservation', 'front_desk'],
  );
  const voidPayment = useHotelMutation<{ id: string; reason: string }, Folio>(
    (h, { id, reason }) => api.post<Folio>(h(`/reservations/${r.id}/payments/${id}/void`), { reason }),
    ['folio', 'reservation', 'payment', 'front_desk'],
  );
  const voidInvoice = useHotelMutation<{ id: string; reason: string }, Invoice>(
    (h, { id, reason }) => api.post<Invoice>(h(`/invoices/${id}/void`), { reason }),
    ['folio', 'invoice', 'reservation'],
  );
  const f = folio.data;
  const money = (v: string | number) => formatMoney(v, r.currency, i18n.language);
  const active = f?.invoices.find((x) => x.status === 'issued');
  const company = useCompanyAccounts().byId(r.company_account_id);
  const transfer = useHotelMutation<void, Folio>(
    (h) => api.post<Folio>(h(`/reservations/${r.id}/transfer-to-account`), {}),
    ['folio', 'reservation', 'payment', 'front_desk', 'invoice', 'company_account'],
  );
  const transferToCompany = () =>
    company &&
    modals.openConfirmModal({
      title: t('accounts.transfer_to', { name: company.name }),
      children: <Text size="sm">{t('accounts.transfer_confirm', { amount: money(r.balance), name: company.name, days: company.payment_terms_days })}</Text>,
      labels: { confirm: t('accounts.transfer'), cancel: t('common.cancel') },
      onConfirm: () => void transfer.mutateAsync().then(() => notifySuccess(t('accounts.transferred', { name: company.name })), notifyError),
    });

  return (
    <Card data-testid="folio">
      <Group justify="space-between" mb="sm" wrap="wrap" gap="xs">
        <Title order={3}>{t('billing.folio')}</Title>
        <Group gap="xs">
          {can('folio.post') && (
            <Button size="xs" variant="light" leftSection={<IconPlus size={14} />} onClick={() => setDialog({ kind: 'charge' })}>
              {t('billing.add_charge')}
            </Button>
          )}
          {can('payments.record') && (
            <Button size="xs" leftSection={<IconCash size={14} />} onClick={() => setDialog({ kind: 'payment' })}>
              {t('billing.take_payment')}
            </Button>
          )}
          {company && can('payments.record') && Number(r.balance) > 0 && (
            <Button size="xs" variant="light" color="indigo" leftSection={<IconBuildingBank size={14} />} onClick={transferToCompany} data-testid="transfer-to-company">
              {t('accounts.transfer_to', { name: company.name })}
            </Button>
          )}
          {can('invoices.issue') && !active && Number(r.grand_total) > 0 && (
            <Button size="xs" variant="default" leftSection={<IconFileInvoice size={14} />} onClick={() => setDialog({ kind: 'invoice' })}>
              {t('billing.issue_invoice')}
            </Button>
          )}
          <PdfMenu path={`/reservations/${r.id}/folio.pdf`} label={t('billing.print_folio')} />
        </Group>
      </Group>

      {f?.invoice_outdated && (
        <Alert color="orange" mb="sm" p="xs">
          <Text size="sm">{t('billing.invoice_outdated', { number: active?.number })}</Text>
        </Alert>
      )}

      <div className="hms-table-wrap">
        <Table miw={560} verticalSpacing={6}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t('billing.description')}</Table.Th>
              <Table.Th ta="right">{t('billing.quantity')}</Table.Th>
              <Table.Th ta="right">{t('billing.unit_price')}</Table.Th>
              <Table.Th ta="right">{t('billing.amount')}</Table.Th>
              <Table.Th w={40} />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {f?.accommodation.map((run) => (
              <Table.Tr key={`${run.reservation_room_id}-${run.start}`}>
                <Table.Td>
                  <Text size="sm">{inv.typeName(run.room_type_id)}</Text>
                  <Text size="xs" c="dimmed">
                    {run.room_id ? t('billing.room_number', { number: inv.roomNumber(run.room_id) }) : t('reservations.unassigned')} · {formatDate(run.start, i18n.language)} →{' '}
                    {formatDate(run.end, i18n.language)}
                  </Text>
                </Table.Td>
                <Table.Td ta="right" className="hms-num">
                  {t('reservations.nights', { count: run.nights })}
                </Table.Td>
                <Table.Td ta="right" className="hms-num">
                  {money(run.unit_price)}
                </Table.Td>
                <Table.Td ta="right" className="hms-num">
                  {money(run.amount)}
                </Table.Td>
                <Table.Td />
              </Table.Tr>
            ))}
            {f?.charges.map((c) => (
              <Table.Tr key={c.id} style={c.is_void ? { opacity: 0.55 } : undefined} data-charge={c.kind}>
                <Table.Td>
                  <Text size="sm" td={c.is_void ? 'line-through' : undefined}>
                    {chargeTitle(c, t, i18n.language, hotel.default_language)}
                  </Text>
                  <Text size="xs" c="dimmed">
                    {formatDate(c.service_date, i18n.language)}
                    {c.kind !== 'service' || pickLocalized(c.name, i18n.language, hotel.default_language) ? (c.description ? ` · ${c.description}` : '') : ''}
                    {c.created_by_name ? ` · ${c.created_by_name}` : ''}
                    {c.is_void ? ` · ${t('billing.voided_by', { name: c.voided_by_name ?? '—', reason: c.void_reason })}` : ''}
                  </Text>
                </Table.Td>
                <Table.Td ta="right" className="hms-num">
                  {formatNumber(c.quantity, i18n.language, 2)}
                </Table.Td>
                <Table.Td ta="right" className="hms-num">
                  {money(c.unit_price)}
                </Table.Td>
                <Table.Td ta="right" className="hms-num" td={c.is_void ? 'line-through' : undefined}>
                  {money(c.amount)}
                </Table.Td>
                <Table.Td>
                  {!c.is_void && can('folio.adjust') && (
                    <Tooltip label={t('billing.void')}>
                      <ActionIcon variant="subtle" color="red" aria-label={t('billing.void')} onClick={() => setDialog({ kind: 'void_charge', id: c.id })}>
                        <IconTrash size={15} />
                      </ActionIcon>
                    </Tooltip>
                  )}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </div>

      {f && (
        <Stack gap={4} mt="sm" ml="auto" maw={360} data-testid="folio-totals">
          <TotalRow label={t('billing.subtotal')} value={money(Number(f.totals.accommodation) + Number(f.totals.charges))} />
          {f.taxes.map((tax) => (
            <TotalRow
              key={`${tax.code}-${tax.is_inclusive}`}
              dimmed
              label={`${pickLocalized(tax.name, i18n.language, hotel.default_language) || tax.code}${tax.is_inclusive ? ` (${t('settings.taxes.included')})` : ''}`}
              value={money(tax.amount)}
            />
          ))}
          <Divider />
          <TotalRow strong label={t('reservations.total')} value={money(f.totals.grand_total)} />
          <TotalRow dimmed label={t('reservations.paid')} value={money(f.totals.paid_total)} />
          <TotalRow
            strong
            label={Number(f.totals.balance) < 0 ? t('billing.credit') : t('reservations.balance')}
            value={money(Math.abs(Number(f.totals.balance)))}
            color={Number(f.totals.balance) > 0 ? 'red.7' : Number(f.totals.balance) < 0 ? 'orange.7' : 'teal.7'}
            testId="folio-balance"
          />
        </Stack>
      )}

      <Title order={4} mt="lg" mb="xs">
        {t('billing.payments')}
      </Title>
      {f && f.payments.length === 0 ? (
        <Text size="sm" c="dimmed">
          {t('billing.no_payments')}
        </Text>
      ) : (
        <div className="hms-table-wrap">
          <Table miw={560} verticalSpacing={6}>
            <Table.Tbody>
              {f?.payments.map((p) => (
                <Table.Tr key={p.id} style={p.is_void ? { opacity: 0.55 } : undefined} data-payment={p.number}>
                  <Table.Td>
                    <Text size="sm" fw={500}>
                      {p.number} · {t(`billing.payment_kinds.${p.kind}`)} · {t(`billing.methods.${p.method}`)}
                      {p.card_last4 ? ` ···· ${p.card_last4}` : ''}
                    </Text>
                    <Text size="xs" c="dimmed">
                      {formatDateTime(p.received_at, i18n.language, hotel.timezone)} · {p.received_by_name ?? '—'}
                      {p.reference ? ` · ${p.reference}` : ''}
                      {p.is_void ? ` · ${t('billing.voided_by', { name: p.voided_by_name ?? '—', reason: p.void_reason })}` : ''}
                    </Text>
                  </Table.Td>
                  <Table.Td ta="right" className="hms-num">
                    <Text size="sm" td={p.is_void ? 'line-through' : undefined} c={p.kind === 'refund' ? 'orange.7' : undefined}>
                      {p.kind === 'refund' ? '−' : ''}
                      {money(p.amount_base)}
                    </Text>
                    {p.currency !== r.currency && (
                      <Text size="xs" c="dimmed">
                        {formatMoney(p.amount, p.currency, i18n.language)} @ {formatNumber(p.exchange_rate, i18n.language, 6)}
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td w={48}>
                    <Menu position="bottom-end" withinPortal>
                      <Menu.Target>
                        <ActionIcon variant="subtle" aria-label={t('common.actions')}>
                          <IconDotsVertical size={16} />
                        </ActionIcon>
                      </Menu.Target>
                      <Menu.Dropdown>
                        <Menu.Item component="a" href={url(`/reservations/${r.id}/payments/${p.id}/receipt.pdf`)} target="_blank" rel="noopener" leftSection={<IconReceipt size={14} />}>
                          {t('billing.receipt')}
                        </Menu.Item>
                        {!p.is_void && can('payments.void') && (
                          <Menu.Item color="red" leftSection={<IconTrash size={14} />} onClick={() => setDialog({ kind: 'void_payment', id: p.id })}>
                            {t('billing.void')}
                          </Menu.Item>
                        )}
                      </Menu.Dropdown>
                    </Menu>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </div>
      )}
      {can('payments.refund') && f && Number(f.totals.paid_total) - Number(f.totals.transferred) > 0 && (
        <Button variant="subtle" color="orange" size="xs" mt="xs" onClick={() => setDialog({ kind: 'payment', refund: true })}>
          {t('billing.refund')}
        </Button>
      )}

      {f && f.invoices.length > 0 && (
        <>
          <Title order={4} mt="lg" mb="xs">
            {t('billing.invoices')}
          </Title>
          <Stack gap={6}>
            {f.invoices.map((x) => (
              <Group key={x.id} justify="space-between" wrap="nowrap" data-invoice={x.number}>
                <div>
                  <Group gap={6}>
                    <Text size="sm" fw={600} td={x.status === 'void' ? 'line-through' : undefined}>
                      {x.number}
                    </Text>
                    {x.status === 'void' && (
                      <Badge color="red" variant="light" size="sm">
                        {t('billing.void_status')}
                      </Badge>
                    )}
                  </Group>
                  <Text size="xs" c="dimmed">
                    {formatDate(x.issue_date, i18n.language)} · {x.bill_to.company || x.bill_to.name} · {money(x.total)}
                    {x.void_reason ? ` · ${x.void_reason}` : ''}
                  </Text>
                </div>
                <Group gap={4} wrap="nowrap">
                  <PdfMenu fixedLanguage path={`/invoices/${x.id}/pdf`} label="PDF" />
                  {x.status === 'issued' && can('invoices.void') && (
                    <Button size="xs" variant="subtle" color="red" onClick={() => setDialog({ kind: 'void_invoice', invoice: x })}>
                      {t('billing.void')}
                    </Button>
                  )}
                </Group>
              </Group>
            ))}
          </Stack>
        </>
      )}

      {dialog?.kind === 'charge' && <ChargeModal reservation={r} onClose={() => setDialog(null)} />}
      {dialog?.kind === 'payment' && (
        <PaymentModal
          reservation={r}
          initialKind={dialog.refund ? 'refund' : 'payment'}
          initialAmount={!dialog.refund && Number(r.balance) > 0 ? r.balance : dialog.refund && Number(r.balance) < 0 ? String(-Number(r.balance)) : undefined}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog?.kind === 'invoice' && <InvoiceModal reservation={r} onClose={() => setDialog(null)} />}
      {dialog?.kind === 'void_charge' && (
        <ReasonModal
          title={t('billing.void_charge')}
          body={t('billing.void_charge_body')}
          confirm={t('billing.void')}
          loading={voidCharge.isPending}
          onClose={() => setDialog(null)}
          onConfirm={(reason) => voidCharge.mutateAsync({ id: dialog.id, reason })}
        />
      )}
      {dialog?.kind === 'void_payment' && (
        <ReasonModal
          title={t('billing.void_payment')}
          body={t('billing.void_payment_body')}
          confirm={t('billing.void')}
          loading={voidPayment.isPending}
          onClose={() => setDialog(null)}
          onConfirm={(reason) => voidPayment.mutateAsync({ id: dialog.id, reason })}
        />
      )}
      {dialog?.kind === 'void_invoice' && (
        <ReasonModal
          title={t('billing.void_invoice', { number: dialog.invoice.number })}
          body={t('billing.void_invoice_body')}
          confirm={t('billing.void')}
          loading={voidInvoice.isPending}
          onClose={() => setDialog(null)}
          onConfirm={(reason) => voidInvoice.mutateAsync({ id: dialog.invoice.id, reason })}
        />
      )}
    </Card>
  );
}

function TotalRow({ label, value, strong, dimmed, color, testId }: { label: string; value: string; strong?: boolean; dimmed?: boolean; color?: string; testId?: string }) {
  return (
    <Group justify="space-between" wrap="nowrap" data-testid={testId}>
      <Text size="sm" fw={strong ? 700 : undefined} c={dimmed ? 'dimmed' : color}>
        {label}
      </Text>
      <Text size="sm" fw={strong ? 700 : undefined} c={dimmed ? 'dimmed' : color} className="hms-num">
        {value}
      </Text>
    </Group>
  );
}
