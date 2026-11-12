import { useState } from 'react';
import { ActionIcon, Alert, Badge, Button, Card, Checkbox, Divider, Group, Loader, Menu, Modal, NumberInput, Select, SimpleGrid, Stack, Text, Textarea, TextInput } from '@mantine/core';
import { DateTimePicker } from '@mantine/dates';
import { IconCash, IconPrinter, IconTrash } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { api } from '@/api/client';
import { useHotelMutation, useHotelQuery } from '@/api/hooks';
import type { DepositKind, Rental } from '@/api/types';
import { useAuth, useHotel } from '@/auth/AuthProvider';
import { SubmitButton } from '@/components/ui';
import { LANGUAGES } from '@/i18n';
import { hotelLocalToIso, isoToHotelLocal } from '@/lib/dates';
import { errorMessage, notifyError, notifySuccess } from '@/lib/errors';
import { formatDateTime, formatMoney } from '@/lib/format';
import { COUNTRY_CODES } from '@/lib/refdata';
import { ReasonModal } from '@/modules/billing/FolioDialogs';
import { SalePaymentModal } from '@/modules/billing/SalePaymentModal';
import { useDocumentUrl } from '@/modules/billing/shared';
import { fuelLabel, RentalStatusBadge } from './shared';

const ENTITIES = ['vehicle_rental', 'vehicle', 'payment'];
const DEPOSITS: DepositKind[] = ['none', 'cash', 'card_hold', 'passport', 'id_card', 'other'];
type Dialog = 'pickup' | 'return' | 'extend' | 'pay' | 'discount' | 'cancel' | { voidPayment: string };

export function RentalDetail({ id }: { id: string }) {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const { can } = useAuth();
  const url = useDocumentUrl();
  const rental = useHotelQuery<Rental>('vehicle_rental', `/vehicle-rentals/${id}`);
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const post = useHotelMutation<{ path: string; body: Record<string, unknown> }, Rental>((h, { path, body }) => api.post<Rental>(h(`/vehicle-rentals/${id}${path}`), body), ENTITIES);
  const r = rental.data;
  if (!r) return <Loader size="sm" />;
  const money = (v: string | number, cur = hotel.currency_code) => formatMoney(v, cur, i18n.language);
  const when = (iso: string | null) => formatDateTime(iso, i18n.language, hotel.timezone);
  const rent = can('vehicles.rent');
  const run = (path: string, body: Record<string, unknown>, done: string) => post.mutateAsync({ path, body }).then(() => notifySuccess(done), notifyError);

  return (
    <Stack data-testid="rental-detail">
      <Group justify="space-between" align="flex-start">
        <div>
          <Text fw={700} size="lg">
            {r.vehicle_label}
          </Text>
          <Text size="sm" c="dimmed">
            {r.number} · {t(`vehicles.kinds.${r.vehicle_kind}`)}
            {r.with_driver ? ` · ${t('vehicles.driver_included')}` : ''}
          </Text>
        </div>
        <RentalStatusBadge status={r.status} overdue={r.overdue} />
      </Group>
      <Card withBorder padding="sm">
        <Text size="sm" fw={600}>
          {r.guest_name}
          {r.room_number ? ` · ${t('restaurant.room_n', { number: r.room_number })}` : ''}
        </Text>
        {r.guest_phone && <Text size="xs" c="dimmed">{r.guest_phone}</Text>}
        <Text size="sm" mt={4}>
          {when(r.start_at)} → {when(r.end_at)}
        </Text>
        {r.picked_up_at && (
          <Text size="xs" c="dimmed">
            {t('vehicles.picked_up_line', { time: when(r.picked_up_at), km: r.odometer_out ?? '—', fuel: fuelLabel(r.fuel_out) })}
            {r.licence_last4 ? ` · ${t('vehicles.licence_line', { last4: r.licence_last4 })}` : ''}
          </Text>
        )}
        {r.condition_out && <Text size="xs" c="dimmed">{r.condition_out}</Text>}
        {r.returned_at && (
          <Text size="xs" c="dimmed">
            {t('vehicles.returned_line', { time: when(r.returned_at), km: r.odometer_in ?? '—', fuel: fuelLabel(r.fuel_in) })}
          </Text>
        )}
        {r.condition_in && <Text size="xs" c="dimmed">{r.condition_in}</Text>}
        {r.deposit_kind !== 'none' && (
          <Group gap={6} mt={4}>
            <Badge size="sm" variant="light" color={r.deposit_returned_at ? 'gray' : 'orange'}>
              {t('vehicles.deposit')} · {t(`vehicles.deposit_kinds.${r.deposit_kind}`)}
              {r.deposit_amount ? ` ${money(r.deposit_amount, r.deposit_currency ?? hotel.currency_code)}` : ''}
              {r.deposit_returned_at ? ` · ${t('vehicles.deposit_returned')}` : ''}
            </Badge>
            {!r.deposit_returned_at && r.status === 'returned' && rent && (
              <Button size="compact-xs" variant="subtle" onClick={() => void run('/deposit-returned', { version: r.version }, t('vehicles.deposit_returned_done'))}>
                {t('vehicles.give_back_deposit')}
              </Button>
            )}
          </Group>
        )}
        {r.notes && <Text size="xs" mt={4}>{r.notes}</Text>}
        {r.cancel_reason && <Text size="xs" c="red">{r.cancel_reason}</Text>}
      </Card>

      <Stack gap={4}>
        <Row label={t('vehicles.vehicle_price')} value={money(r.base_amount)} />
        {Number(r.driver_amount) > 0 && <Row label={t('vehicles.driver')} value={money(r.driver_amount)} />}
        {Number(r.late_fee) > 0 && <Row label={t('vehicles.late_fee')} value={money(r.late_fee)} />}
        {Number(r.fuel_charge) > 0 && <Row label={t('vehicles.fuel_charge')} value={money(r.fuel_charge)} />}
        {Number(r.damage_charge) > 0 && <Row label={`${t('vehicles.damage')}${r.damage_note ? ` (${r.damage_note})` : ''}`} value={money(r.damage_charge)} />}
        {Number(r.discount_amount) > 0 && <Row label={`${t('restaurant.discount')}${r.discount_reason ? ` (${r.discount_reason})` : ''}`} value={`−${money(r.discount_amount)}`} />}
        {r.tax_breakdown.map((tax) => (
          <Row key={tax.code} dimmed label={`${tax.code} ${Number(tax.rate)}%${tax.is_inclusive ? ` (${t('settings.taxes.included')})` : ''}`} value={money(tax.amount)} />
        ))}
        <Divider />
        <Row strong label={t('reservations.total')} value={money(r.total)} testId="rental-total" />
        <Row dimmed label={t('reservations.paid')} value={money(r.paid_total)} />
        <Row strong label={t('reservations.balance')} value={money(r.balance)} testId="rental-balance" />
      </Stack>
      {r.payments.length > 0 && (
        <Stack gap={2}>
          {r.payments.map((p) => (
            <Group key={p.id} justify="space-between" wrap="nowrap" style={p.is_void ? { opacity: 0.5 } : undefined}>
              <Text size="xs" td={p.is_void ? 'line-through' : undefined}>
                {p.method === 'room_charge' ? t('restaurant.charged_to_room', { room: p.room_number ?? '—' }) : t(`billing.methods.${p.method}`)}
                {p.currency !== hotel.currency_code ? ` · ${money(p.amount, p.currency)}` : ''}
                {p.received_by_name ? ` · ${p.received_by_name}` : ''}
              </Text>
              <Group gap={4} wrap="nowrap">
                <Text size="xs" className="hms-num">
                  {money(p.amount_base)}
                </Text>
                {!p.is_void && can('vehicles.manage') && (
                  <ActionIcon size="xs" variant="subtle" color="red" aria-label={t('billing.void')} onClick={() => setDialog({ voidPayment: p.id })}>
                    <IconTrash size={12} />
                  </ActionIcon>
                )}
              </Group>
            </Group>
          ))}
        </Stack>
      )}

      <Group gap="xs" wrap="wrap">
        {rent && r.status === 'reserved' && (
          <Button onClick={() => setDialog('pickup')} data-action="pickup">
            {t('vehicles.hand_over')}
          </Button>
        )}
        {rent && r.status === 'out' && (
          <Button color="teal" onClick={() => setDialog('return')} data-action="return">
            {t('vehicles.take_back')}
          </Button>
        )}
        {rent && (r.status === 'reserved' || r.status === 'out') && (
          <Button variant="default" onClick={() => setDialog('extend')}>
            {t('vehicles.change_end')}
          </Button>
        )}
        {rent && Number(r.balance) > 0 && r.status !== 'cancelled' && r.status !== 'no_show' && (
          <Button variant="light" color="teal" leftSection={<IconCash size={16} />} onClick={() => setDialog('pay')}>
            {t('restaurant.pay', { amount: money(r.balance) })}
          </Button>
        )}
        {can('vehicles.manage') && r.status !== 'cancelled' && r.status !== 'no_show' && (
          <Button variant="subtle" onClick={() => setDialog('discount')}>
            {t('restaurant.discount')}
          </Button>
        )}
        {rent && r.status === 'reserved' && (
          <>
            <Button variant="subtle" color="red" onClick={() => setDialog('cancel')}>
              {t('vehicles.cancel_rental')}
            </Button>
            {new Date(r.start_at) < new Date() && (
              <Button variant="subtle" color="gray" onClick={() => void run('/no-show', { version: r.version }, t('vehicles.no_show_done'))}>
                {t('vehicles.no_show')}
              </Button>
            )}
          </>
        )}
        <Menu position="bottom-end" withinPortal>
          <Menu.Target>
            <Button variant="default" leftSection={<IconPrinter size={16} />}>
              {t('vehicles.contract')}
            </Button>
          </Menu.Target>
          <Menu.Dropdown>
            {LANGUAGES.map((l) => (
              <Menu.Item key={l.code} component="a" href={url(`/vehicle-rentals/${r.id}/contract.pdf`, l.code)} target="_blank" rel="noopener">
                {l.label}
              </Menu.Item>
            ))}
          </Menu.Dropdown>
        </Menu>
      </Group>

      {dialog === 'pickup' && <PickupModal rental={r} onClose={() => setDialog(null)} />}
      {dialog === 'return' && <ReturnModal rental={r} onClose={() => setDialog(null)} />}
      {dialog === 'extend' && <ExtendModal rental={r} onClose={() => setDialog(null)} />}
      {dialog === 'discount' && <DiscountModal rental={r} onClose={() => setDialog(null)} />}
      {dialog === 'pay' && (
        <SalePaymentModal
          path={`/vehicle-rentals/${r.id}/payments`}
          balance={r.balance}
          allowRoomCharge={r.status === 'returned' && Number(r.paid_total) === 0}
          defaultGuest={r.in_house ? r.reservation_room_id : null}
          roomChargeHint={t('vehicles.room_charge_hint')}
          invalidates={ENTITIES}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog === 'cancel' && (
        <ReasonModal
          title={t('vehicles.cancel_rental')}
          body={t('vehicles.cancel_body')}
          confirm={t('vehicles.cancel_rental')}
          loading={post.isPending}
          onClose={() => setDialog(null)}
          onConfirm={(reason) => post.mutateAsync({ path: '/cancel', body: { version: r.version, reason } })}
        />
      )}
      {dialog && typeof dialog === 'object' && (
        <ReasonModal
          title={t('billing.void_payment')}
          body={t('vehicles.void_payment_body')}
          confirm={t('billing.void')}
          loading={post.isPending}
          onClose={() => setDialog(null)}
          onConfirm={(reason) => post.mutateAsync({ path: `/payments/${dialog.voidPayment}/void`, body: { reason } })}
        />
      )}
    </Stack>
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

function useRentalAction(id: string, path: string) {
  return useHotelMutation<Record<string, unknown>, Rental>((h, body) => api.post<Rental>(h(`/vehicle-rentals/${id}${path}`), body), ENTITIES);
}

function PickupModal({ rental: r, onClose }: { rental: Rental; onClose: () => void }) {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const [licence, setLicence] = useState('');
  const [country, setCountry] = useState<string | null>(null);
  const [expiry, setExpiry] = useState('');
  const [odometer, setOdometer] = useState<number | string>(r.odometer_out ?? r.vehicle_odometer);
  const [fuel, setFuel] = useState<string | null>('8');
  const [condition, setCondition] = useState('');
  const [deposit, setDeposit] = useState<DepositKind>('none');
  const [depositAmount, setDepositAmount] = useState<number | string>('');
  const [depositNote, setDepositNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  const save = useRentalAction(r.id, '/pickup');
  const regions = new Intl.DisplayNames([i18n.language], { type: 'region' });
  return (
    <Modal opened onClose={onClose} title={t('vehicles.hand_over')} size="lg">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          save
            .mutateAsync({
              version: r.version,
              odometer_out: Number(odometer),
              fuel_out: fuel === null ? undefined : Number(fuel),
              condition_out: condition.trim() || undefined,
              licence_number: licence.trim() || undefined,
              licence_country: country ?? undefined,
              licence_expiry: expiry || undefined,
              deposit_kind: deposit,
              deposit_amount: depositAmount === '' ? undefined : String(depositAmount),
              deposit_note: depositNote.trim() || undefined,
            })
            .then(() => {
              notifySuccess(t('vehicles.handed_over_done'));
              onClose();
            }, (err) => setError(errorMessage(err)));
        }}
      >
        <Stack>
          {error && <Alert color="red">{error}</Alert>}
          {r.licence_required && (
            <SimpleGrid cols={{ base: 1, sm: 3 }}>
              <TextInput label={t('vehicles.licence_number')} description={t('vehicles.licence_hint')} required value={licence} onChange={(e) => setLicence(e.currentTarget.value)} maxLength={40} data-autofocus />
              <Select label={t('vehicles.licence_country')} searchable clearable data={COUNTRY_CODES.map((c) => ({ value: c, label: regions.of(c) ?? c }))} value={country} onChange={setCountry} />
              <TextInput label={t('vehicles.licence_expiry')} type="date" value={expiry} onChange={(e) => setExpiry(e.currentTarget.value)} />
            </SimpleGrid>
          )}
          <SimpleGrid cols={2}>
            <NumberInput label={t('vehicles.odometer')} required min={0} value={odometer} onChange={setOdometer} suffix=" km" />
            <Select label={t('vehicles.fuel')} data={Array.from({ length: 9 }, (_, i) => ({ value: String(i), label: `${i}/8` }))} value={fuel} onChange={setFuel} />
          </SimpleGrid>
          <Textarea label={t('vehicles.condition')} placeholder={t('vehicles.condition_placeholder')} autosize minRows={2} value={condition} onChange={(e) => setCondition(e.currentTarget.value)} />
          <SimpleGrid cols={{ base: 1, sm: 3 }}>
            <Select label={t('vehicles.deposit')} allowDeselect={false} data={DEPOSITS.map((d) => ({ value: d, label: t(`vehicles.deposit_kinds.${d}`) }))} value={deposit} onChange={(v) => v && setDeposit(v as DepositKind)} />
            {(deposit === 'cash' || deposit === 'card_hold') && (
              <NumberInput label={t('billing.amount')} min={0} decimalScale={2} value={depositAmount} onChange={setDepositAmount} placeholder={hotel.currency_code} />
            )}
            {deposit !== 'none' && <TextInput label={t('billing.notes')} maxLength={200} value={depositNote} onChange={(e) => setDepositNote(e.currentTarget.value)} />}
          </SimpleGrid>
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <SubmitButton loading={save.isPending} disabled={odometer === '' || (r.licence_required && !licence.trim())}>
              {t('vehicles.hand_over')}
            </SubmitButton>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

function ReturnModal({ rental: r, onClose }: { rental: Rental; onClose: () => void }) {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const { can } = useAuth();
  const [odometer, setOdometer] = useState<number | string>(r.odometer_out ?? '');
  const [fuel, setFuel] = useState<string | null>(r.fuel_out !== null ? String(r.fuel_out) : null);
  const [condition, setCondition] = useState('');
  const [fuelCharge, setFuelCharge] = useState<number | string>(0);
  const [damage, setDamage] = useState<number | string>(0);
  const [damageNote, setDamageNote] = useState('');
  const [waive, setWaive] = useState(false);
  const [depositBack, setDepositBack] = useState(true);
  const [maintenance, setMaintenance] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const save = useRentalAction(r.id, '/return');
  return (
    <Modal opened onClose={onClose} title={t('vehicles.take_back')} size="lg">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          save
            .mutateAsync({
              version: r.version,
              odometer_in: Number(odometer),
              fuel_in: fuel === null ? undefined : Number(fuel),
              condition_in: condition.trim() || undefined,
              fuel_charge: String(fuelCharge || 0),
              damage_charge: String(damage || 0),
              damage_note: damageNote.trim() || undefined,
              waive_late_fee: waive,
              deposit_returned: depositBack,
              vehicle_needs_maintenance: maintenance,
            })
            .then((res) => {
              notifySuccess(Number(res.late_fee) > 0 ? t('vehicles.returned_late_done', { fee: formatMoney(res.late_fee, hotel.currency_code, i18n.language) }) : t('vehicles.returned_done'));
              onClose();
            }, (err) => setError(errorMessage(err)));
        }}
      >
        <Stack>
          {error && <Alert color="red">{error}</Alert>}
          {r.overdue && <Alert color="orange">{t('vehicles.late_hint')}</Alert>}
          <SimpleGrid cols={2}>
            <NumberInput label={t('vehicles.odometer')} required min={r.odometer_out ?? 0} value={odometer} onChange={setOdometer} suffix=" km" data-autofocus />
            <Select label={t('vehicles.fuel')} data={Array.from({ length: 9 }, (_, i) => ({ value: String(i), label: `${i}/8` }))} value={fuel} onChange={setFuel} />
          </SimpleGrid>
          <Textarea label={t('vehicles.condition')} autosize minRows={2} value={condition} onChange={(e) => setCondition(e.currentTarget.value)} />
          <SimpleGrid cols={{ base: 1, sm: 3 }}>
            <NumberInput label={t('vehicles.fuel_charge')} min={0} decimalScale={2} value={fuelCharge} onChange={setFuelCharge} />
            <NumberInput label={t('vehicles.damage')} min={0} decimalScale={2} value={damage} onChange={setDamage} />
            <TextInput label={t('vehicles.damage_note')} maxLength={300} value={damageNote} onChange={(e) => setDamageNote(e.currentTarget.value)} />
          </SimpleGrid>
          {r.overdue && can('vehicles.manage') && <Checkbox label={t('vehicles.waive_late_fee')} checked={waive} onChange={(e) => setWaive(e.currentTarget.checked)} />}
          {r.deposit_kind !== 'none' && <Checkbox label={t('vehicles.deposit_given_back')} checked={depositBack} onChange={(e) => setDepositBack(e.currentTarget.checked)} />}
          <Checkbox label={t('vehicles.needs_maintenance')} checked={maintenance} onChange={(e) => setMaintenance(e.currentTarget.checked)} />
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <SubmitButton color="teal" loading={save.isPending} disabled={odometer === ''}>
              {t('vehicles.take_back')}
            </SubmitButton>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

function ExtendModal({ rental: r, onClose }: { rental: Rental; onClose: () => void }) {
  const { t } = useTranslation();
  const hotel = useHotel();
  const [end, setEnd] = useState<string | null>(isoToHotelLocal(r.end_at, hotel.timezone));
  const [error, setError] = useState<string | null>(null);
  const save = useHotelMutation<Record<string, unknown>, Rental>((h, body) => api.patch<Rental>(h(`/vehicle-rentals/${r.id}`), body), ENTITIES);
  return (
    <Modal opened onClose={onClose} title={t('vehicles.change_end')}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!end) return;
          save.mutateAsync({ version: r.version, end_at: hotelLocalToIso(end, hotel.timezone) }).then(() => {
            notifySuccess(t('common.saved'));
            onClose();
          }, (err) => setError(errorMessage(err)));
        }}
      >
        <Stack>
          {error && <Alert color="red">{error}</Alert>}
          <DateTimePicker label={t('vehicles.end')} value={end} onChange={setEnd} valueFormat="ddd D MMM YYYY HH:mm" />
          <Text size="xs" c="dimmed">
            {t('vehicles.change_end_hint')}
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <SubmitButton loading={save.isPending} disabled={!end}>
              {t('common.save')}
            </SubmitButton>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

function DiscountModal({ rental: r, onClose }: { rental: Rental; onClose: () => void }) {
  const { t } = useTranslation();
  const [amount, setAmount] = useState<number | string>(Number(r.discount_amount) || '');
  const [reason, setReason] = useState(r.discount_reason ?? '');
  const [error, setError] = useState<string | null>(null);
  const save = useRentalAction(r.id, '/discount');
  return (
    <Modal opened onClose={onClose} title={t('restaurant.discount')}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          save.mutateAsync({ version: r.version, amount: String(amount || 0), reason: reason.trim() || undefined }).then(() => {
            notifySuccess(t('common.saved'));
            onClose();
          }, (err) => setError(errorMessage(err)));
        }}
      >
        <Stack>
          {error && <Alert color="red">{error}</Alert>}
          <NumberInput label={t('billing.amount')} min={0} decimalScale={2} value={amount} onChange={setAmount} />
          <TextInput label={t('billing.reason')} maxLength={300} value={reason} onChange={(e) => setReason(e.currentTarget.value)} />
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <SubmitButton loading={save.isPending}>{t('common.save')}</SubmitButton>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}
