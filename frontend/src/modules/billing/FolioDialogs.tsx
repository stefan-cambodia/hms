import { useMemo, useRef, useState } from 'react';
import { Alert, Button, Group, Modal, NumberInput, SegmentedControl, Select, SimpleGrid, Stack, Text, Textarea, TextInput } from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { api, ApiError } from '@/api/client';
import { useHotelMutation, useHotelQuery } from '@/api/hooks';
import { hotelKey } from '@/api/realtime';
import type { ChargeKind, FeeType, Folio, FolioPart, FolioTotals, Invoice, Payment, PaymentKind, PaymentMethod, Reservation, Service } from '@/api/types';
import { useAuth, useHotel } from '@/auth/AuthProvider';
import { SubmitButton } from '@/components/ui';
import { daysBetween } from '@/lib/dates';
import { applyFieldErrors, errorMessage, notifySuccess } from '@/lib/errors';
import { formatMoney, formatNumber } from '@/lib/format';
import { pickLocalized } from '@/lib/localized';
import { newIdempotencyKey, useHotelToday } from '@/modules/reservations/shared';
import { CARD_BRANDS, defaultQuantity, FEE_TYPES, languageOptions, PAYMENT_METHODS, toBase, usePaymentCurrencies } from './shared';

const FOLIO_ENTITIES = ['folio', 'reservation', 'payment', 'front_desk'];

type Res = Pick<Reservation, 'id' | 'currency' | 'balance' | 'rooms'>;

// --- payment -----------------------------------------------------------------------

export function PaymentModal({
  reservation: r,
  initialKind = 'payment',
  initialAmount,
  parts,
  initialPart = 'guest',
  onClose,
  onDone,
}: {
  reservation: Res;
  initialKind?: PaymentKind;
  initialAmount?: string;
  /** Split folio: the parts' totals; the payment goes to one of them. */
  parts?: Record<FolioPart, FolioTotals> | null;
  initialPart?: FolioPart;
  onClose: () => void;
  onDone?: (p: Payment) => void;
}) {
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const qc = useQueryClient();
  const hotel = useHotel();
  const currencies = usePaymentCurrencies();
  const [kind, setKind] = useState<PaymentKind>(initialKind);
  const [part, setPart] = useState<FolioPart>(initialPart);
  const [method, setMethod] = useState<PaymentMethod>('cash');
  const [currency, setCurrency] = useState(r.currency);
  const [amount, setAmount] = useState<number | string>(initialAmount ? Number(initialAmount) : '');
  const [brand, setBrand] = useState<string | null>(null);
  const [last4, setLast4] = useState('');
  const [reference, setReference] = useState('');
  const [notes, setNotes] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const key = useRef(newIdempotencyKey());
  const rate = currencies.rate(currency);
  const base = toBase(Number(amount), rate);

  const save = useHotelMutation<Record<string, unknown>, Payment>(
    (h, body) => api.post<Payment>(h(`/reservations/${r.id}/payments`), body, { 'Idempotency-Key': key.current }),
    FOLIO_ENTITIES,
  );

  const changeCurrency = (code: string) => {
    // Keep the same value when switching currency for a prefilled balance.
    if (initialAmount && amount !== '' && Number(amount) === Number(initialAmount) && code !== r.currency) {
      const units = currencies.rate(code);
      if (units) setAmount(Math.round(Number(initialAmount) * Number(units) * 100) / 100);
    } else if (code === r.currency && initialAmount) setAmount(Number(initialAmount));
    setCurrency(code);
  };

  const submit = async () => {
    setError(null);
    setErrors({});
    const body: Record<string, unknown> = {
      kind,
      method,
      amount: String(amount),
      currency,
      exchange_rate: currency !== r.currency ? rate : undefined,
      reference: reference.trim() || undefined,
      notes: notes.trim() || undefined,
      card_brand: method === 'card' ? brand || undefined : undefined,
      card_last4: method === 'card' ? last4.trim() || undefined : undefined,
      folio: parts ? part : undefined,
    };
    try {
      const p = await save.mutateAsync(body);
      notifySuccess(t(kind === 'refund' ? 'billing.refund_done' : 'billing.payment_done', { number: p.number }));
      onDone?.(p);
      onClose();
    } catch (err) {
      if (!(err instanceof ApiError) || !err.isNetwork) key.current = newIdempotencyKey();
      if (err instanceof ApiError && err.code === 'EXCHANGE_RATE_CHANGED') void qc.invalidateQueries({ queryKey: hotelKey(hotel.id, 'currency') });
      const map: Record<string, string> = {};
      if (!applyFieldErrors(err, (k, m) => (map[k] = m))) setError(errorMessage(err));
      setErrors(map);
    }
  };

  const kinds: PaymentKind[] = can('payments.refund') ? ['payment', 'deposit', 'refund'] : ['payment', 'deposit'];
  return (
    <Modal opened onClose={onClose} title={t(kind === 'refund' ? 'billing.refund_title' : 'billing.payment_title')} size="lg">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <Stack>
          {error && <Alert color="red">{error}</Alert>}
          <SegmentedControl value={kind} onChange={(v) => setKind(v as PaymentKind)} data={kinds.map((k) => ({ value: k, label: t(`billing.payment_kinds.${k}`) }))} />
          {parts && (
            <SegmentedControl
              value={part}
              data-testid="payment-part"
              onChange={(v) => {
                const next = v as FolioPart;
                setPart(next);
                // Prefilled with the part's balance: follow the part chosen.
                const due = Number(parts[next].balance);
                if (currency === r.currency) setAmount(kind === 'refund' ? (due < 0 ? -due : '') : due > 0 ? due : '');
              }}
              data={(['guest', 'company'] as const).map((p) => ({ value: p, label: t(`billing.parts.${p}`) }))}
            />
          )}
          <Text size="sm" c="dimmed">
            {t('billing.current_balance')}: <b className="hms-num">{formatMoney(parts ? parts[part].balance : r.balance, r.currency, i18n.language)}</b>
          </Text>
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <Select
              label={t('billing.method')}
              allowDeselect={false}
              data={PAYMENT_METHODS.map((m) => ({ value: m, label: t(`billing.methods.${m}`) }))}
              value={method}
              onChange={(v) => v && setMethod(v as PaymentMethod)}
            />
            <Select label={t('billing.currency')} allowDeselect={false} data={currencies.list} value={currency} onChange={(v) => v && changeCurrency(v)} />
          </SimpleGrid>
          <NumberInput
            label={t('billing.amount')}
            required
            min={0.01}
            decimalScale={2}
            thousandSeparator=","
            value={amount}
            onChange={setAmount}
            error={errors.amount}
            data-autofocus
            rightSection={<Text size="xs" c="dimmed">{currency}</Text>}
            rightSectionWidth={48}
          />
          {currency !== r.currency && (
            <Text size="sm" c="dimmed" data-testid="conversion">
              {t('billing.rate_line', { base: r.currency, rate: rate ? formatNumber(rate, i18n.language, 6) : '—', currency })} ·{' '}
              {t('billing.equivalent')}: <b className="hms-num">{base !== null ? formatMoney(base, r.currency, i18n.language) : '—'}</b>
            </Text>
          )}
          {method === 'card' && (
            <SimpleGrid cols={{ base: 1, sm: 2 }}>
              <Select
                label={t('billing.card_brand')}
                clearable
                data={CARD_BRANDS.map((b) => ({ value: b, label: t(`billing.card_brands.${b}`) }))}
                value={brand}
                onChange={setBrand}
              />
              <TextInput
                label={t('billing.card_last4')}
                description={t('billing.card_last4_hint')}
                maxLength={4}
                inputMode="numeric"
                value={last4}
                onChange={(e) => setLast4(e.currentTarget.value.replace(/\D/g, ''))}
                error={errors.card_last4}
              />
            </SimpleGrid>
          )}
          <TextInput label={t('billing.reference')} description={t('billing.reference_hint')} maxLength={100} value={reference} onChange={(e) => setReference(e.currentTarget.value)} error={errors.reference} />
          <Textarea label={t('billing.notes')} autosize minRows={1} maxLength={500} value={notes} onChange={(e) => setNotes(e.currentTarget.value)} error={errors.notes} />
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <SubmitButton loading={save.isPending} disabled={!(Number(amount) > 0)} color={kind === 'refund' ? 'orange' : undefined}>
              {t(kind === 'refund' ? 'billing.record_refund' : 'billing.record_payment')}
            </SubmitButton>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

// --- charge ------------------------------------------------------------------------

export function ChargeModal({ reservation: r, onClose }: { reservation: Res; onClose: () => void }) {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const { can } = useAuth();
  const today = useHotelToday();
  const services = useHotelQuery<Service[]>('service', '/services');
  const kinds: ChargeKind[] = can('folio.adjust') ? ['service', 'fee', 'adjustment'] : ['service', 'fee'];
  const [kind, setKind] = useState<ChargeKind>('service');
  const [serviceId, setServiceId] = useState<string | null>(null);
  const [feeType, setFeeType] = useState<FeeType>('late_checkout');
  const [description, setDescription] = useState('');
  const [quantity, setQuantity] = useState<number | string>(1);
  const [unitPrice, setUnitPrice] = useState<number | string>('');
  const [date, setDate] = useState<string | null>(today);
  const [stayId, setStayId] = useState<string | null>(r.rooms.length === 1 ? r.rooms[0].id : null);
  const [error, setError] = useState<string | null>(null);
  const key = useRef(newIdempotencyKey());
  const active = useMemo(() => (services.data ?? []).filter((s) => s.is_active), [services.data]);
  const save = useHotelMutation<Record<string, unknown>, Folio>(
    (h, body) => api.post<Folio>(h(`/reservations/${r.id}/charges`), body, { 'Idempotency-Key': key.current }),
    FOLIO_ENTITIES,
  );

  const pickService = (id: string | null) => {
    setServiceId(id);
    const s = active.find((x) => x.id === id);
    if (!s) return;
    const stay = r.rooms.find((x) => x.id === stayId) ?? r.rooms[0];
    const nights = stay ? daysBetween(stay.arrival, stay.departure) : 1;
    const persons = stay ? stay.adults + stay.children : 1;
    setQuantity(defaultQuantity(s.pricing_unit, nights, persons));
    setUnitPrice(Number(s.price));
  };
  const amount = Number(quantity) * Number(unitPrice || 0);
  const valid =
    Number(quantity) > 0 &&
    unitPrice !== '' &&
    (kind === 'service' ? !!serviceId || !!description.trim() : kind === 'fee' ? true : !!description.trim() && Number(unitPrice) !== 0);

  const submit = async () => {
    setError(null);
    const body: Record<string, unknown> = {
      kind,
      quantity: String(quantity),
      unit_price: String(unitPrice),
      service_date: date ?? undefined,
      reservation_room_id: stayId ?? undefined,
      description: description.trim() || undefined,
    };
    if (kind === 'service' && serviceId) body.service_id = serviceId;
    if (kind === 'fee') body.fee_type = feeType;
    try {
      await save.mutateAsync(body);
      notifySuccess(t('billing.charge_done'));
      onClose();
    } catch (err) {
      if (!(err instanceof ApiError) || !err.isNetwork) key.current = newIdempotencyKey();
      setError(errorMessage(err));
    }
  };

  return (
    <Modal opened onClose={onClose} title={t('billing.add_charge')} size="lg">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (valid) void submit();
        }}
      >
        <Stack>
          {error && <Alert color="red">{error}</Alert>}
          <SegmentedControl value={kind} onChange={(v) => setKind(v as ChargeKind)} data={kinds.map((k) => ({ value: k, label: t(`billing.charge_kinds.${k}`) }))} />
          {kind === 'service' && (
            <Select
              label={t('billing.service')}
              description={t('billing.service_hint')}
              searchable
              clearable
              data={active.map((s) => ({ value: s.id, label: `${pickLocalized(s.name, i18n.language, hotel.default_language)} · ${formatMoney(s.price, hotel.currency_code, i18n.language)}` }))}
              value={serviceId}
              onChange={pickService}
              nothingFoundMessage={t('common.no_results')}
            />
          )}
          {kind === 'fee' && (
            <Select
              label={t('billing.fee_type')}
              allowDeselect={false}
              data={FEE_TYPES.map((f) => ({ value: f, label: t(`billing.fee_types.${f}`) }))}
              value={feeType}
              onChange={(v) => v && setFeeType(v as FeeType)}
            />
          )}
          <TextInput
            label={kind === 'service' && !serviceId ? t('billing.item_name') : t('billing.description')}
            required={(kind === 'service' && !serviceId) || kind === 'adjustment'}
            maxLength={300}
            value={description}
            onChange={(e) => setDescription(e.currentTarget.value)}
          />
          <SimpleGrid cols={{ base: 1, sm: 3 }}>
            <NumberInput label={t('billing.quantity')} min={0.01} decimalScale={2} value={quantity} onChange={setQuantity} required />
            <NumberInput
              label={kind === 'adjustment' ? t('billing.adjustment_amount') : t('billing.unit_price')}
              description={kind === 'adjustment' ? t('billing.adjustment_hint') : undefined}
              decimalScale={2}
              min={kind === 'adjustment' ? undefined : 0}
              value={unitPrice}
              onChange={setUnitPrice}
              required
            />
            <DatePickerInput label={t('billing.service_date')} value={date} onChange={setDate} valueFormat="D MMM YYYY" />
          </SimpleGrid>
          {r.rooms.length > 1 && (
            <Select
              label={t('billing.stay')}
              clearable
              data={r.rooms.map((rr, i) => ({ value: rr.id, label: `${i + 1}. ${rr.arrival} → ${rr.departure}` }))}
              value={stayId}
              onChange={setStayId}
            />
          )}
          <Text size="sm">
            {t('billing.amount')}: <b className="hms-num">{formatMoney(amount, r.currency, i18n.language)}</b>
            {kind === 'service' ? <Text span size="xs" c="dimmed"> · {t('billing.service_tax_hint')}</Text> : <Text span size="xs" c="dimmed"> · {t('billing.untaxed_hint')}</Text>}
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <SubmitButton loading={save.isPending} disabled={!valid}>
              {t('billing.post_charge')}
            </SubmitButton>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

// --- void / reason -------------------------------------------------------------------

export function ReasonModal({
  title,
  body,
  confirm,
  loading,
  onClose,
  onConfirm,
}: {
  title: string;
  body: string;
  confirm: string;
  loading: boolean;
  onClose: () => void;
  onConfirm: (reason: string) => Promise<unknown>;
}) {
  const { t } = useTranslation();
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);
  return (
    <Modal opened onClose={onClose} title={title}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!reason.trim()) return;
          onConfirm(reason.trim()).then(onClose, (err) => setError(errorMessage(err)));
        }}
      >
        <Stack>
          {error && <Alert color="red">{error}</Alert>}
          <Text size="sm">{body}</Text>
          <Textarea label={t('billing.reason')} required autosize minRows={2} maxLength={500} value={reason} onChange={(e) => setReason(e.currentTarget.value)} data-autofocus />
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <SubmitButton color="red" loading={loading} disabled={!reason.trim()}>
              {confirm}
            </SubmitButton>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

// --- invoice ----------------------------------------------------------------------

export function InvoiceModal({
  reservation,
  parts,
  companyAccount,
  onClose,
  onDone,
}: {
  reservation: Reservation;
  /** Split folio: the parts that can still be invoiced (one invoice each). */
  parts?: FolioPart[];
  companyAccount?: string;
  onClose: () => void;
  onDone?: (inv: Invoice) => void;
}) {
  const { t } = useTranslation();
  const [part, setPart] = useState<FolioPart | undefined>(parts?.[0]);
  const b = reservation.booker;
  // 'auto': the server uses the guest's preferred language, else the hotel's.
  const [language, setLanguage] = useState<string>('auto');
  const [company, setCompany] = useState(false);
  const [name, setName] = useState(`${b.first_name} ${b.last_name}`);
  const [companyName, setCompanyName] = useState('');
  const [taxId, setTaxId] = useState('');
  const [address, setAddress] = useState('');
  const [city, setCity] = useState('');
  const [error, setError] = useState<string | null>(null);
  const issue = useHotelMutation<Record<string, unknown>, Invoice>((h, body) => api.post<Invoice>(h(`/reservations/${reservation.id}/invoices`), body), ['invoice', 'folio', 'reservation']);
  const submit = () => {
    const body: Record<string, unknown> = { language: language === 'auto' ? undefined : language, folio: part };
    // The company's part is always made out to the company account.
    if (company && part !== 'company')
      body.bill_to = {
        name: name.trim(),
        company: companyName.trim() || undefined,
        tax_id: taxId.trim() || undefined,
        address: address.trim() || undefined,
        city: city.trim() || undefined,
      };
    issue.mutateAsync(body).then(
      (inv) => {
        notifySuccess(t('billing.invoice_done', { number: inv.number }));
        onDone?.(inv);
        onClose();
      },
      (err) => setError(errorMessage(err)),
    );
  };
  return (
    <Modal opened onClose={onClose} title={t('billing.issue_invoice')}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <Stack>
          {error && <Alert color="red">{error}</Alert>}
          <Text size="sm" c="dimmed">
            {t('billing.invoice_hint')}
          </Text>
          {parts && parts.length > 0 && (
            <SegmentedControl
              value={part}
              onChange={(v) => setPart(v as FolioPart)}
              data-testid="invoice-part"
              data={(['guest', 'company'] as const).map((p) => ({ value: p, label: t(`billing.parts.${p}`), disabled: !parts.includes(p) }))}
            />
          )}
          <Select
            label={t('billing.document_language')}
            allowDeselect={false}
            data={[{ value: 'auto', label: t('billing.guest_language') }, ...languageOptions()]}
            value={language}
            onChange={(v) => v && setLanguage(v)}
          />
          {part === 'company' ? (
            <Alert color="indigo" variant="light" p="xs">
              <Text size="sm">{t('billing.made_out_to', { name: companyAccount ?? '' })}</Text>
            </Alert>
          ) : (
            <SegmentedControl
              value={company ? 'company' : 'guest'}
              onChange={(v) => setCompany(v === 'company')}
              data={[
                { value: 'guest', label: t('billing.bill_guest') },
                { value: 'company', label: t('billing.bill_company') },
              ]}
            />
          )}
          {company && part !== 'company' && (
            <>
              <TextInput label={t('billing.bill_name')} required value={name} onChange={(e) => setName(e.currentTarget.value)} maxLength={200} />
              <TextInput label={t('billing.company')} value={companyName} onChange={(e) => setCompanyName(e.currentTarget.value)} maxLength={200} />
              <TextInput label={t('billing.tax_id')} value={taxId} onChange={(e) => setTaxId(e.currentTarget.value)} maxLength={60} />
              <TextInput label={t('billing.address')} value={address} onChange={(e) => setAddress(e.currentTarget.value)} maxLength={300} />
              <TextInput label={t('billing.city')} value={city} onChange={(e) => setCity(e.currentTarget.value)} maxLength={100} />
            </>
          )}
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <SubmitButton loading={issue.isPending} disabled={company && part !== 'company' && !name.trim()}>
              {t('billing.issue')}
            </SubmitButton>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}
