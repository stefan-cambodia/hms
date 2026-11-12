import { useMemo, useRef, useState } from 'react';
import { Alert, Button, Card, Drawer, Group, SegmentedControl, Select, SimpleGrid, Stack, Switch, Text, Textarea, Title } from '@mantine/core';
import { DateTimePicker } from '@mantine/dates';
import { useTranslation } from 'react-i18next';

import { api, ApiError } from '@/api/client';
import { useHotelMutation, useHotelQuery } from '@/api/hooks';
import type { GuestRef, Rental, RentalQuote, Vehicle } from '@/api/types';
import { useHotel } from '@/auth/AuthProvider';
import { SubmitButton } from '@/components/ui';
import { addDays, hotelLocalToIso, hotelToday } from '@/lib/dates';
import { errorMessage, notifySuccess } from '@/lib/errors';
import { formatMoney } from '@/lib/format';
import { EMPTY_GUEST, type GuestChoice, GuestPicker } from '@/modules/reservations/GuestPicker';
import { newIdempotencyKey } from '@/modules/reservations/shared';

export interface RentalDraft {
  vehicle_id?: string;
  day?: string; // YYYY-MM-DD (hotel)
}

/** Next full hour in the hotel's zone, as "YYYY-MM-DD HH:00:00". */
function nextHour(timeZone: string, day?: string): string {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone, hourCycle: 'h23', hour: '2-digit' }).formatToParts(new Date());
  const hour = Math.min(23, Number(parts.find((p) => p.type === 'hour')?.value ?? 8) + 1);
  const today = hotelToday(timeZone);
  if (day && day !== today) return `${day} 09:00:00`;
  return `${today} ${String(hour).padStart(2, '0')}:00:00`;
}

function plusOneDay(local: string): string {
  const [d, t] = local.split(' ');
  return `${addDays(d, 1)} ${t}`;
}

export function NewRentalDrawer({ draft, onClose, onCreated }: { draft: RentalDraft | null; onClose: () => void; onCreated: (id: string) => void }) {
  const { t } = useTranslation();
  return (
    <Drawer opened={!!draft} onClose={onClose} position="right" size="lg" title={<Title order={3}>{t('vehicles.new_rental')}</Title>}>
      {draft && <RentalForm draft={draft} onDone={(id) => (onClose(), onCreated(id))} onCancel={onClose} />}
    </Drawer>
  );
}

function RentalForm({ draft, onDone, onCancel }: { draft: RentalDraft; onDone: (id: string) => void; onCancel: () => void }) {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const initialStart = nextHour(hotel.timezone, draft.day);
  const [start, setStart] = useState<string | null>(initialStart);
  const [end, setEnd] = useState<string | null>(plusOneDay(initialStart));
  const [vehicleId, setVehicleId] = useState<string | null>(draft.vehicle_id ?? null);
  const [withDriver, setWithDriver] = useState(false);
  const [mode, setMode] = useState<'in_house' | 'other'>('in_house');
  const [stay, setStay] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [guest, setGuest] = useState<GuestChoice>({ mode: 'new', data: EMPTY_GUEST });
  const [notes, setNotes] = useState('');
  const [error, setError] = useState<string | null>(null);
  const key = useRef(newIdempotencyKey());
  const startIso = start ? hotelLocalToIso(start, hotel.timezone) : null;
  const endIso = end ? hotelLocalToIso(end, hotel.timezone) : null;
  const validPeriod = !!startIso && !!endIso && endIso > startIso;
  const fleet = useHotelQuery<Vehicle[]>('vehicle', '/vehicles', { start: startIso, end: endIso }, validPeriod);
  const vehicle = fleet.data?.find((v) => v.id === vehicleId);
  const quote = useHotelQuery<RentalQuote>(
    'vehicle_rental',
    '/vehicle-rentals/quote',
    { vehicle_id: vehicleId, start: startIso, end: endIso, with_driver: withDriver },
    validPeriod && !!vehicleId && !!vehicle?.available,
  );
  const guests = useHotelQuery<GuestRef[]>('reservation', '/in-house-guests', { q: search || undefined }, mode === 'in_house');
  const create = useHotelMutation<Record<string, unknown>, Rental>(
    (h, body) => api.post<Rental>(h('/vehicle-rentals'), body, { 'Idempotency-Key': key.current }),
    ['vehicle_rental', 'vehicle'],
  );
  const vehicleOptions = useMemo(
    () =>
      (fleet.data ?? [])
        .filter((v) => v.status !== 'retired')
        .map((v) => ({
          value: v.id,
          label: `${v.code} · ${t(`vehicles.kinds.${v.kind}`)}${v.make ? ` · ${[v.make, v.model].filter(Boolean).join(' ')}` : ''} · ${formatMoney(v.daily_rate, hotel.currency_code, i18n.language)}/${t('vehicles.day')}${
            v.available === false ? ` — ${t(`vehicles.unavailable.${v.unavailable_reason}`)}` : ''
          }`,
          disabled: v.available === false,
        })),
    [fleet.data, t, hotel.currency_code, i18n.language],
  );
  const customerOk = mode === 'in_house' ? !!stay : guest.mode === 'existing' ? !!guest.guest : !!(guest.data.first_name.trim() && guest.data.last_name.trim());
  const valid = validPeriod && !!vehicle?.available && customerOk;

  const submit = () => {
    setError(null);
    const customer =
      mode === 'in_house'
        ? { reservation_room_id: stay }
        : guest.mode === 'existing'
          ? { guest_id: guest.guest?.id }
          : {
              guest: {
                first_name: guest.data.first_name.trim(),
                last_name: guest.data.last_name.trim(),
                email: guest.data.email.trim() || null,
                phone: guest.data.phone.trim() || null,
                nationality: guest.data.nationality,
                preferred_language: guest.data.preferred_language,
              },
            };
    create.mutateAsync({ vehicle_id: vehicleId, start_at: startIso, end_at: endIso, with_driver: withDriver, notes: notes.trim() || undefined, ...customer }).then(
      (r) => {
        notifySuccess(t('vehicles.created_done', { number: r.number }));
        onDone(r.id);
      },
      (err) => {
        if (!(err instanceof ApiError) || !err.isNetwork) key.current = newIdempotencyKey();
        setError(errorMessage(err));
      },
    );
  };

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (valid) submit();
      }}
    >
      <Stack>
        {error && <Alert color="red">{error}</Alert>}
        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          <DateTimePicker label={t('vehicles.start')} value={start} onChange={setStart} valueFormat="ddd D MMM YYYY HH:mm" required />
          <DateTimePicker label={t('vehicles.end')} value={end} onChange={setEnd} valueFormat="ddd D MMM YYYY HH:mm" minDate={start ?? undefined} required error={start && end && !validPeriod ? t('vehicles.end_after_start') : undefined} />
        </SimpleGrid>
        <Select label={t('vehicles.vehicle')} searchable required data={vehicleOptions} value={vehicleId} onChange={setVehicleId} nothingFoundMessage={t('vehicles.no_vehicle')} />
        {vehicle?.driver_daily_rate && (
          <Switch label={t('vehicles.with_driver', { rate: formatMoney(vehicle.driver_daily_rate, hotel.currency_code, i18n.language) })} checked={withDriver} onChange={(e) => setWithDriver(e.currentTarget.checked)} />
        )}
        <SegmentedControl
          value={mode}
          onChange={(v) => setMode(v as typeof mode)}
          data={[
            { value: 'in_house', label: t('vehicles.hotel_guest') },
            { value: 'other', label: t('vehicles.other_customer') },
          ]}
        />
        {mode === 'in_house' ? (
          <Select
            label={t('restaurant.guest_room')}
            searchable
            searchValue={search}
            onSearchChange={setSearch}
            data={(guests.data ?? []).map((g) => ({ value: g.reservation_room_id, label: `${g.room_number ?? '—'} · ${g.guest_name}` }))}
            value={stay}
            onChange={setStay}
            nothingFoundMessage={t('restaurant.no_guest_found')}
          />
        ) : (
          <GuestPicker value={guest} onChange={setGuest} />
        )}
        <Textarea label={t('vehicles.notes')} autosize minRows={1} maxLength={2000} value={notes} onChange={(e) => setNotes(e.currentTarget.value)} />
        {quote.data && (
          <Card withBorder padding="sm" data-testid="rental-quote">
            <Group justify="space-between">
              <Text size="sm">{t('vehicles.duration', { hours: quote.data.hours, days: quote.data.charge_days })}</Text>
              <Text fw={700} className="hms-num">
                {formatMoney(quote.data.total, hotel.currency_code, i18n.language)}
              </Text>
            </Group>
            {Number(quote.data.deposit_amount) > 0 && (
              <Text size="xs" c="dimmed">
                {t('vehicles.deposit_hint', { amount: formatMoney(quote.data.deposit_amount, hotel.currency_code, i18n.language) })}
              </Text>
            )}
          </Card>
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={onCancel}>
            {t('common.cancel')}
          </Button>
          <SubmitButton loading={create.isPending} disabled={!valid}>
            {t('vehicles.create')}
          </SubmitButton>
        </Group>
      </Stack>
    </form>
  );
}
