import { useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import {
  ActionIcon,
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Divider,
  Grid,
  Group,
  Menu,
  Modal,
  NumberInput,
  ScrollArea,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
  Title,
  UnstyledButton,
} from '@mantine/core';
import { IconArrowLeft, IconCash, IconDots, IconMinus, IconPlus, IconPrinter, IconSend, IconTrash } from '@tabler/icons-react';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';

import { api, ApiError } from '@/api/client';
import { useHotelMutation, useHotelQuery } from '@/api/hooks';
import type { DiningTable, GuestRef, OrderLine, PosMethod, RestaurantOrder } from '@/api/types';
import { PageLoader } from '@/app/AppLayout';
import { useAuth, useHotel } from '@/auth/AuthProvider';
import { EmptyState, SubmitButton } from '@/components/ui';
import { LANGUAGES } from '@/i18n';
import { errorMessage, notifyError, notifySuccess } from '@/lib/errors';
import { formatMoney, formatNumber } from '@/lib/format';
import { ReasonModal } from '@/modules/billing/FolioDialogs';
import { CARD_BRANDS, toBase, useDocumentUrl, usePaymentCurrencies } from '@/modules/billing/shared';
import { newIdempotencyKey } from '@/modules/reservations/shared';
import { LineStatusBadge, useLocalized, useMenu } from './shared';

type Dialog = { kind: 'pay' } | { kind: 'discount' } | { kind: 'move' } | { kind: 'cancel' } | { kind: 'void_line'; line: OrderLine } | { kind: 'void_payment'; id: string };

export default function OrderPage() {
  const { id } = useParams();
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const { can } = useAuth();
  const navigate = useNavigate();
  const loc = useLocalized();
  const url = useDocumentUrl();
  const order = useHotelQuery<RestaurantOrder>('restaurant_order', `/restaurant/orders/${id}`);
  const o = order.data;
  const menu = useMenu(o?.outlet_id);
  const [category, setCategory] = useState<string | null>(null);
  const [filter, setFilter] = useState('');
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const call = useHotelMutation<{ method: 'post' | 'patch' | 'delete'; path: string; body?: unknown; key?: string }, RestaurantOrder>(
    (h, { method, path, body, key }) =>
      method === 'post'
        ? api.post<RestaurantOrder>(h(`/restaurant/orders/${id}${path}`), body ?? {}, key ? { 'Idempotency-Key': key } : undefined)
        : method === 'patch'
          ? api.patch<RestaurantOrder>(h(`/restaurant/orders/${id}${path}`), body)
          : api.delete<RestaurantOrder>(h(`/restaurant/orders/${id}${path}`)),
    ['restaurant_order'],
  );
  const run = (method: 'post' | 'patch' | 'delete', path: string, body?: unknown, done?: string) =>
    call.mutateAsync({ method, path, body, key: path === '/lines' ? newIdempotencyKey() : undefined }).then((r) => {
      if (done) notifySuccess(done);
      return r;
    }, notifyError);

  const visibleItems = useMemo(() => {
    const q = filter.trim().toLowerCase();
    return menu.items.filter((i) => (q ? loc(i.name).toLowerCase().includes(q) : !category || i.category_id === category));
  }, [menu.items, category, filter, loc]);

  if (order.isPending) return <PageLoader />;
  if (!o) return <EmptyState title={t('restaurant.order_not_found')} />;
  const money = (v: string | number) => formatMoney(v, hotel.currency_code, i18n.language);
  const isOpen = o.status === 'open';
  const canOrder = can('restaurant.order') && isOpen;
  const newLines = o.lines.filter((l) => l.status === 'new');
  const back = `/restaurant/floor?outlet=${o.outlet_id}`;

  return (
    <>
      <Anchor component={Link} to={back} size="sm" c="dimmed">
        <Group gap={4}>
          <IconArrowLeft size={14} />
          {t('restaurant.back_to_floor')}
        </Group>
      </Anchor>
      <Group justify="space-between" mt="xs" mb="md" wrap="wrap">
        <div>
          <Group gap="sm">
            <Title order={2}>
              {o.table_label ? t('restaurant.table_n', { table: o.table_label }) : t(`restaurant.order_types.${o.order_type}`)}
            </Title>
            <Badge color={isOpen ? 'blue' : o.status === 'closed' ? 'teal' : 'gray'} variant="light">
              {t(`restaurant.order_status.${o.status}`)}
            </Badge>
          </Group>
          <Text size="sm" c="dimmed">
            {o.number} · {t('restaurant.covers_n', { count: o.covers })}
            {o.opened_by_name ? ` · ${o.opened_by_name}` : ''}
            {o.guest ? ` · ${t('restaurant.room_n', { number: o.guest.room_number })} ${o.guest.guest_name}` : ''}
          </Text>
        </div>
        <Group gap="xs">
          <Menu position="bottom-end" withinPortal>
            <Menu.Target>
              <Button variant="default" leftSection={<IconPrinter size={16} />}>
                {isOpen ? t('restaurant.print_bill') : t('restaurant.print_receipt')}
              </Button>
            </Menu.Target>
            <Menu.Dropdown>
              {LANGUAGES.map((l) => (
                <Menu.Item key={l.code} component="a" href={url(`/restaurant/orders/${o.id}/bill.pdf`, l.code)} target="_blank" rel="noopener">
                  {l.label}
                </Menu.Item>
              ))}
            </Menu.Dropdown>
          </Menu>
          {isOpen && (
            <Menu position="bottom-end" withinPortal>
              <Menu.Target>
                <ActionIcon variant="default" size="lg" aria-label={t('common.actions')}>
                  <IconDots size={18} />
                </ActionIcon>
              </Menu.Target>
              <Menu.Dropdown>
                {can('restaurant.order') && o.table_id && <Menu.Item onClick={() => setDialog({ kind: 'move' })}>{t('restaurant.move_table')}</Menu.Item>}
                {can('restaurant.void') && <Menu.Item onClick={() => setDialog({ kind: 'discount' })}>{t('restaurant.discount')}</Menu.Item>}
                {can('restaurant.order') && (
                  <Menu.Item color="red" onClick={() => setDialog({ kind: 'cancel' })}>
                    {t('restaurant.cancel_order')}
                  </Menu.Item>
                )}
              </Menu.Dropdown>
            </Menu>
          )}
        </Group>
      </Group>

      <Grid gutter="md">
        {canOrder && (
          <Grid.Col span={{ base: 12, md: 7 }}>
            <Card padding="sm">
              <TextInput placeholder={t('restaurant.search_menu')} value={filter} onChange={(e) => setFilter(e.currentTarget.value)} mb="xs" />
              <ScrollArea type="auto" mb="xs">
                <SegmentedControl
                  value={category ?? 'all'}
                  onChange={(v) => setCategory(v === 'all' ? null : v)}
                  data={[{ value: 'all', label: t('restaurant.all_items') }, ...menu.categories.map((c) => ({ value: c.id, label: loc(c.name) }))]}
                />
              </ScrollArea>
              <SimpleGrid cols={{ base: 2, sm: 3, lg: 4 }} spacing="xs">
                {visibleItems.map((item) => (
                  <UnstyledButton
                    key={item.id}
                    disabled={!item.is_available || call.isPending}
                    onClick={() => void run('post', '/lines', { items: [{ menu_item_id: item.id, quantity: 1 }] })}
                    data-menu-item={loc(item.name)}
                  >
                    <Card withBorder padding="sm" style={{ minHeight: 76, opacity: item.is_available ? 1 : 0.45 }}>
                      <Text fw={600} size="sm" lineClamp={2}>
                        {loc(item.name)}
                      </Text>
                      <Group justify="space-between" mt={4}>
                        <Text size="sm" className="hms-num">
                          {money(item.price)}
                        </Text>
                        {!item.is_available && (
                          <Badge size="xs" color="red" variant="light">
                            {t('restaurant.sold_out')}
                          </Badge>
                        )}
                      </Group>
                    </Card>
                  </UnstyledButton>
                ))}
              </SimpleGrid>
              {visibleItems.length === 0 && <Text c="dimmed" size="sm">{t('restaurant.no_items')}</Text>}
            </Card>
          </Grid.Col>
        )}
        <Grid.Col span={{ base: 12, md: canOrder ? 5 : 12 }}>
          <Card padding="sm" data-testid="check">
            <Stack gap={6}>
              {o.lines.length === 0 && <Text c="dimmed" size="sm">{t('restaurant.empty_check')}</Text>}
              {o.lines.map((line) => (
                <Group key={line.id} justify="space-between" wrap="nowrap" align="flex-start" data-line={loc(line.name)} style={line.status === 'void' ? { opacity: 0.5 } : undefined}>
                  <div style={{ minWidth: 0 }}>
                    <Group gap={6} wrap="nowrap">
                      <Text size="sm" fw={600} td={line.status === 'void' ? 'line-through' : undefined}>
                        {line.quantity} × {loc(line.name)}
                      </Text>
                      <LineStatusBadge status={line.status} />
                    </Group>
                    {(line.notes || line.void_reason) && (
                      <Text size="xs" c="dimmed">
                        {line.void_reason ?? line.notes}
                      </Text>
                    )}
                  </div>
                  <Group gap={4} wrap="nowrap">
                    {line.status === 'new' && canOrder && (
                      <>
                        <ActionIcon size="sm" variant="default" aria-label="-1" disabled={line.quantity <= 1} onClick={() => void run('patch', `/lines/${line.id}`, { quantity: line.quantity - 1 })}>
                          <IconMinus size={12} />
                        </ActionIcon>
                        <ActionIcon size="sm" variant="default" aria-label="+1" onClick={() => void run('patch', `/lines/${line.id}`, { quantity: line.quantity + 1 })}>
                          <IconPlus size={12} />
                        </ActionIcon>
                        <ActionIcon size="sm" variant="subtle" color="red" aria-label={t('common.delete')} onClick={() => void run('delete', `/lines/${line.id}`)}>
                          <IconTrash size={14} />
                        </ActionIcon>
                      </>
                    )}
                    {line.status !== 'new' && line.status !== 'void' && isOpen && can('restaurant.void') && (
                      <ActionIcon size="sm" variant="subtle" color="red" aria-label={t('restaurant.void_item')} onClick={() => setDialog({ kind: 'void_line', line })}>
                        <IconTrash size={14} />
                      </ActionIcon>
                    )}
                    <Text size="sm" className="hms-num" w={76} ta="right" td={line.status === 'void' ? 'line-through' : undefined}>
                      {money(line.amount)}
                    </Text>
                  </Group>
                </Group>
              ))}
              <Divider my={4} />
              <Row label={t('restaurant.subtotal')} value={money(o.subtotal)} />
              {Number(o.discount_total) > 0 && <Row label={`${t('restaurant.discount')}${o.discount_reason ? ` (${o.discount_reason})` : ''}`} value={`−${money(o.discount_total)}`} />}
              {Number(o.service_charge) > 0 && <Row label={t('restaurant.service_charge', { rate: formatNumber(o.service_charge_percent, i18n.language, 2) })} value={money(o.service_charge)} />}
              {o.tax_breakdown.map((tax) => (
                <Row key={tax.code} dimmed label={`${loc(tax.name) || tax.code} ${formatNumber(tax.rate, i18n.language, 2)}%${tax.is_inclusive ? ` (${t('settings.taxes.included')})` : ''}`} value={money(tax.amount)} />
              ))}
              <Row strong label={t('reservations.total')} value={money(o.total)} testId="check-total" />
              {Number(o.paid_total) > 0 && <Row dimmed label={t('reservations.paid')} value={money(o.paid_total)} />}
              {isOpen && Number(o.paid_total) > 0 && <Row strong label={t('reservations.balance')} value={money(o.balance)} />}
              {o.payments.length > 0 && (
                <Stack gap={2} mt={4}>
                  {o.payments.map((p) => (
                    <Group key={p.id} justify="space-between" wrap="nowrap" style={p.is_void ? { opacity: 0.5 } : undefined}>
                      <Text size="xs" td={p.is_void ? 'line-through' : undefined}>
                        {p.method === 'room_charge' ? t('restaurant.charged_to_room', { room: p.room_number ?? '—' }) : t(`billing.methods.${p.method}`)}
                        {p.currency !== hotel.currency_code ? ` · ${formatMoney(p.amount, p.currency, i18n.language)}` : ''}
                        {p.tendered ? ` · ${t('restaurant.tendered_change', { tendered: formatMoney(p.tendered, p.currency, i18n.language), change: formatMoney(Number(p.tendered) - Number(p.amount), p.currency, i18n.language) })}` : ''}
                      </Text>
                      <Group gap={4} wrap="nowrap">
                        <Text size="xs" className="hms-num">
                          {money(p.amount_base)}
                        </Text>
                        {!p.is_void && o.status !== 'cancelled' && can('restaurant.void') && (
                          <ActionIcon size="xs" variant="subtle" color="red" aria-label={t('billing.void')} onClick={() => setDialog({ kind: 'void_payment', id: p.id })}>
                            <IconTrash size={12} />
                          </ActionIcon>
                        )}
                      </Group>
                    </Group>
                  ))}
                </Stack>
              )}
              {o.cancel_reason && <Alert color="gray" p="xs">{o.cancel_reason}</Alert>}
              {isOpen && (
                <Stack gap="xs" mt="sm">
                  {newLines.length > 0 && can('restaurant.order') && (
                    <Button size="md" leftSection={<IconSend size={18} />} loading={call.isPending} onClick={() => void run('post', '/send', undefined, t('restaurant.sent_done'))}>
                      {t('restaurant.send', { count: newLines.reduce((n, l) => n + l.quantity, 0) })}
                    </Button>
                  )}
                  {o.lines_ready > 0 && can('restaurant.order') && (
                    <Button size="md" variant="light" color="teal" loading={call.isPending} onClick={() => void run('post', '/served', undefined, t('restaurant.served_done'))}>
                      {t('restaurant.mark_served', { count: o.lines_ready })}
                    </Button>
                  )}
                  {can('restaurant.settle') && Number(o.balance) > 0 && (
                    <Button size="md" color="teal" leftSection={<IconCash size={18} />} disabled={newLines.length > 0} title={newLines.length > 0 ? t('restaurant.send_first') : undefined} onClick={() => setDialog({ kind: 'pay' })}>
                      {t('restaurant.pay', { amount: money(o.balance) })}
                    </Button>
                  )}
                </Stack>
              )}
            </Stack>
          </Card>
        </Grid.Col>
      </Grid>

      {dialog?.kind === 'pay' && <PayModal order={o} onClose={() => setDialog(null)} />}
      {dialog?.kind === 'discount' && <DiscountModal order={o} onClose={() => setDialog(null)} onSave={(body) => run('post', '/discount', body, t('common.saved'))} />}
      {dialog?.kind === 'move' && <MoveModal order={o} onClose={() => setDialog(null)} onSave={(tableId) => run('patch', '', { version: o.version, table_id: tableId }, t('restaurant.moved_done'))} />}
      {dialog?.kind === 'cancel' && (
        <ReasonModal
          title={t('restaurant.cancel_order')}
          body={t('restaurant.cancel_body')}
          confirm={t('restaurant.cancel_order')}
          loading={call.isPending}
          onClose={() => setDialog(null)}
          onConfirm={(reason) => call.mutateAsync({ method: 'post', path: '/cancel', body: { reason } }).then(() => navigate(back))}
        />
      )}
      {dialog?.kind === 'void_line' && (
        <ReasonModal
          title={t('restaurant.void_item')}
          body={t('restaurant.void_item_body', { item: `${dialog.line.quantity} × ${loc(dialog.line.name)}` })}
          confirm={t('billing.void')}
          loading={call.isPending}
          onClose={() => setDialog(null)}
          onConfirm={(reason) => call.mutateAsync({ method: 'post', path: `/lines/${dialog.line.id}/void`, body: { reason } })}
        />
      )}
      {dialog?.kind === 'void_payment' && (
        <ReasonModal
          title={t('billing.void_payment')}
          body={t('restaurant.void_payment_body')}
          confirm={t('billing.void')}
          loading={call.isPending}
          onClose={() => setDialog(null)}
          onConfirm={(reason) => call.mutateAsync({ method: 'post', path: `/payments/${dialog.id}/void`, body: { reason } })}
        />
      )}
    </>
  );
}

function Row({ label, value, strong, dimmed, testId }: { label: string; value: string; strong?: boolean; dimmed?: boolean; testId?: string }) {
  return (
    <Group justify="space-between" wrap="nowrap" data-testid={testId}>
      <Text size="sm" fw={strong ? 700 : undefined} c={dimmed ? 'dimmed' : undefined}>
        {label}
      </Text>
      <Text size="sm" fw={strong ? 700 : undefined} c={dimmed ? 'dimmed' : undefined} className="hms-num">
        {value}
      </Text>
    </Group>
  );
}

function PayModal({ order: o, onClose }: { order: RestaurantOrder; onClose: () => void }) {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const currencies = usePaymentCurrencies();
  const [method, setMethod] = useState<PosMethod>('cash');
  const [currency, setCurrency] = useState(hotel.currency_code);
  const [amount, setAmount] = useState<number | string>(Number(o.balance));
  const [brand, setBrand] = useState<string | null>(null);
  const [last4, setLast4] = useState('');
  const [reference, setReference] = useState('');
  const [guest, setGuest] = useState<string | null>(o.guest?.in_house ? o.guest.reservation_room_id : null);
  const [search, setSearch] = useState('');
  const [error, setError] = useState<string | null>(null);
  const key = useRef(newIdempotencyKey());
  const guests = useHotelQuery<GuestRef[]>('reservation', '/restaurant/in-house', { q: search || undefined }, method === 'room_charge');
  const pay = useHotelMutation<Record<string, unknown>, RestaurantOrder>(
    (h, body) => api.post<RestaurantOrder>(h(`/restaurant/orders/${o.id}/payments`), body, { 'Idempotency-Key': key.current }),
    ['restaurant_order', 'payment'],
  );
  const rate = currencies.rate(currency);
  const due = Number(o.balance);
  const dueInCurrency = rate ? Math.round(due * Number(rate) * 100) / 100 : due;
  const base = toBase(Number(amount), rate);
  const change = method === 'cash' && base !== null && base > due ? Number(amount) - dueInCurrency : 0;
  const roomCharge = method === 'room_charge';
  const allowRoom = Number(o.paid_total) === 0;
  const valid = roomCharge ? !!guest : Number(amount) > 0;

  const submit = () => {
    setError(null);
    const body: Record<string, unknown> = roomCharge
      ? { method, reservation_room_id: guest }
      : {
          method,
          amount: String(amount),
          currency,
          exchange_rate: currency !== hotel.currency_code ? rate : undefined,
          reference: reference.trim() || undefined,
          card_brand: method === 'card' ? brand || undefined : undefined,
          card_last4: method === 'card' ? last4 || undefined : undefined,
        };
    pay.mutateAsync(body).then(
      (r) => {
        const last = r.payments.filter((p) => !p.is_void).at(-1);
        if (r.change_due && Number(r.change_due) > 0 && last) {
          // Stays on screen long enough to count the change.
          notifications.show({ color: 'teal', autoClose: 15000, title: t('restaurant.paid_done'), message: t('restaurant.give_change', { amount: formatMoney(r.change_due, last.currency, i18n.language) }) });
        } else {
          notifySuccess(r.status === 'closed' ? t('restaurant.paid_done') : t('restaurant.part_paid_done', { amount: formatMoney(r.balance, hotel.currency_code, i18n.language) }));
        }
        onClose();
      },
      (err) => {
        if (!(err instanceof ApiError) || !err.isNetwork) key.current = newIdempotencyKey();
        setError(errorMessage(err));
      },
    );
  };

  const methods: PosMethod[] = ['cash', 'card', 'bank_transfer', ...(allowRoom ? (['room_charge'] as PosMethod[]) : []), 'other'];
  return (
    <Modal opened onClose={onClose} title={t('restaurant.payment_title', { amount: formatMoney(o.balance, hotel.currency_code, i18n.language) })} size="lg">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (valid) submit();
        }}
      >
        <Stack>
          {error && <Alert color="red">{error}</Alert>}
          <SegmentedControl
            value={method}
            onChange={(v) => setMethod(v as PosMethod)}
            data={methods.map((m) => ({ value: m, label: m === 'room_charge' ? t('restaurant.room_charge') : t(`billing.methods.${m}`) }))}
            fullWidth
          />
          {roomCharge ? (
            <>
              <Select
                label={t('restaurant.guest_room')}
                searchable
                searchValue={search}
                onSearchChange={setSearch}
                data={(guests.data ?? []).map((g) => ({ value: g.reservation_room_id, label: `${g.room_number ?? '—'} · ${g.guest_name}` }))}
                value={guest}
                onChange={setGuest}
                nothingFoundMessage={t('restaurant.no_guest_found')}
              />
              <Text size="sm" c="dimmed">
                {t('restaurant.room_charge_hint')}
              </Text>
            </>
          ) : (
            <>
              <Group grow align="flex-end">
                <Select
                  label={t('billing.currency')}
                  allowDeselect={false}
                  data={currencies.list}
                  value={currency}
                  onChange={(v) => {
                    if (!v) return;
                    setCurrency(v);
                    const r = currencies.rate(v);
                    if (r) setAmount(Math.round(due * Number(r) * 100) / 100);
                  }}
                />
                <NumberInput label={t('billing.amount')} min={0.01} decimalScale={2} thousandSeparator="," value={amount} onChange={setAmount} data-autofocus />
              </Group>
              {currency !== hotel.currency_code && (
                <Text size="sm" c="dimmed">
                  {t('restaurant.due_in', { amount: formatMoney(dueInCurrency, currency, i18n.language) })}
                </Text>
              )}
              {change > 0 && (
                <Alert color="teal" p="xs" data-testid="change">
                  {t('restaurant.give_change', { amount: formatMoney(change, currency, i18n.language) })}
                </Alert>
              )}
              {method === 'card' && (
                <Group grow>
                  <Select label={t('billing.card_brand')} clearable data={CARD_BRANDS.map((b) => ({ value: b, label: t(`billing.card_brands.${b}`) }))} value={brand} onChange={setBrand} />
                  <TextInput label={t('billing.card_last4')} maxLength={4} inputMode="numeric" value={last4} onChange={(e) => setLast4(e.currentTarget.value.replace(/\D/g, ''))} />
                </Group>
              )}
              {method !== 'cash' && <TextInput label={t('billing.reference')} maxLength={100} value={reference} onChange={(e) => setReference(e.currentTarget.value)} />}
            </>
          )}
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <SubmitButton color="teal" loading={pay.isPending} disabled={!valid}>
              {roomCharge ? t('restaurant.charge_room') : t('billing.record_payment')}
            </SubmitButton>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

function DiscountModal({ order: o, onClose, onSave }: { order: RestaurantOrder; onClose: () => void; onSave: (body: Record<string, unknown>) => Promise<unknown> }) {
  const { t } = useTranslation();
  const [kind, setKind] = useState<'percent' | 'amount'>((o.discount_kind as 'percent' | 'amount') ?? 'percent');
  const [value, setValue] = useState<number | string>(o.discount_value ? Number(o.discount_value) : 10);
  const [reason, setReason] = useState(o.discount_reason ?? '');
  return (
    <Modal opened onClose={onClose} title={t('restaurant.discount')}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void onSave({ kind, value: String(value), reason: reason.trim() }).then(onClose);
        }}
      >
        <Stack>
          <SegmentedControl
            value={kind}
            onChange={(v) => setKind(v as typeof kind)}
            data={[
              { value: 'percent', label: '%' },
              { value: 'amount', label: t('restaurant.fixed_amount') },
            ]}
          />
          <NumberInput label={t('restaurant.discount_value')} min={0} max={kind === 'percent' ? 100 : undefined} decimalScale={2} value={value} onChange={setValue} />
          <TextInput label={t('billing.reason')} required maxLength={300} value={reason} onChange={(e) => setReason(e.currentTarget.value)} />
          <Group justify="space-between">
            {o.discount_kind ? (
              <Button variant="subtle" color="red" onClick={() => void onSave({ kind: null }).then(onClose)}>
                {t('restaurant.remove_discount')}
              </Button>
            ) : (
              <span />
            )}
            <Group gap="xs">
              <Button variant="default" onClick={onClose}>
                {t('common.cancel')}
              </Button>
              <SubmitButton disabled={!reason.trim() || !(Number(value) > 0)}>{t('common.save')}</SubmitButton>
            </Group>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

function MoveModal({ order: o, onClose, onSave }: { order: RestaurantOrder; onClose: () => void; onSave: (tableId: string) => Promise<unknown> }) {
  const { t } = useTranslation();
  const tables = useHotelQuery<DiningTable[]>('restaurant_outlet', '/restaurant/tables', { outlet_id: o.outlet_id });
  const [table, setTable] = useState<string | null>(null);
  return (
    <Modal opened onClose={onClose} title={t('restaurant.move_table')}>
      <Stack>
        <Select
          label={t('restaurant.new_table')}
          data={(tables.data ?? []).filter((x) => x.is_active && x.id !== o.table_id).map((x) => ({ value: x.id, label: x.label }))}
          value={table}
          onChange={setTable}
        />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button disabled={!table} onClick={() => table && void onSave(table).then(onClose)}>
            {t('restaurant.move_table')}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
