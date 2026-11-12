import { useRef, useState } from 'react';
import { Alert, Button, Group, Modal, NumberInput, SegmentedControl, Select, Stack, Text, TextInput } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';

import { api, ApiError } from '@/api/client';
import { useHotelMutation, useHotelQuery } from '@/api/hooks';
import type { GuestRef, PosMethod } from '@/api/types';
import { useHotel } from '@/auth/AuthProvider';
import { SubmitButton } from '@/components/ui';
import { errorMessage, notifySuccess } from '@/lib/errors';
import { formatMoney } from '@/lib/format';
import { newIdempotencyKey } from '@/modules/reservations/shared';
import { CARD_BRANDS, toBase, usePaymentCurrencies } from './shared';

interface SaleResult {
  balance: string;
  change_due: string | null;
  payments: { is_void: boolean; currency: string }[];
}

/**
 * Settling a sale outside the room folio (restaurant check, vehicle rental):
 * cash with change, card, transfer, foreign currency, or charge to an
 * in-house guest's room. The server applies the rules; this is the form.
 */
export function SalePaymentModal({
  path,
  balance,
  allowRoomCharge,
  defaultGuest,
  roomChargeHint,
  invalidates,
  onClose,
}: {
  path: string;
  balance: string;
  allowRoomCharge: boolean;
  defaultGuest: string | null;
  roomChargeHint: string;
  invalidates: string[];
  onClose: () => void;
}) {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const currencies = usePaymentCurrencies();
  const [method, setMethod] = useState<PosMethod>('cash');
  const [currency, setCurrency] = useState(hotel.currency_code);
  const [amount, setAmount] = useState<number | string>(Number(balance));
  const [brand, setBrand] = useState<string | null>(null);
  const [last4, setLast4] = useState('');
  const [reference, setReference] = useState('');
  const [guest, setGuest] = useState<string | null>(defaultGuest);
  const [search, setSearch] = useState('');
  const [error, setError] = useState<string | null>(null);
  const key = useRef(newIdempotencyKey());
  const guests = useHotelQuery<GuestRef[]>('reservation', '/in-house-guests', { q: search || undefined }, method === 'room_charge');
  const pay = useHotelMutation<Record<string, unknown>, SaleResult>((h, body) => api.post<SaleResult>(h(path), body, { 'Idempotency-Key': key.current }), invalidates);
  const rate = currencies.rate(currency);
  const due = Number(balance);
  const dueInCurrency = rate ? Math.round(due * Number(rate) * 100) / 100 : due;
  const base = toBase(Number(amount), rate);
  const change = method === 'cash' && base !== null && base > due ? Number(amount) - dueInCurrency : 0;
  const roomCharge = method === 'room_charge';
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
          notifySuccess(Number(r.balance) <= 0 ? t('restaurant.paid_done') : t('restaurant.part_paid_done', { amount: formatMoney(r.balance, hotel.currency_code, i18n.language) }));
        }
        onClose();
      },
      (err) => {
        if (!(err instanceof ApiError) || !err.isNetwork) key.current = newIdempotencyKey();
        setError(errorMessage(err));
      },
    );
  };

  const methods: PosMethod[] = ['cash', 'card', 'bank_transfer', ...(allowRoomCharge ? (['room_charge'] as PosMethod[]) : []), 'other'];
  return (
    <Modal opened onClose={onClose} title={t('restaurant.payment_title', { amount: formatMoney(balance, hotel.currency_code, i18n.language) })} size="lg">
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
                {roomChargeHint}
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
