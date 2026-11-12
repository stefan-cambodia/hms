import { useMemo, useRef, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  Divider,
  Drawer,
  Grid,
  Group,
  NumberInput,
  Select,
  SimpleGrid,
  Stack,
  Text,
  Textarea,
  TextInput,
  Title,
} from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import { useDebouncedValue } from '@mantine/hooks';
import { modals } from '@mantine/modals';
import { IconAlertTriangle, IconPlus, IconTrash } from '@tabler/icons-react';
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { api, ApiError } from '@/api/client';
import { useHotelQuery } from '@/api/hooks';
import { hotelKey } from '@/api/realtime';
import type { Availability, AvailableRoom, Offer, Quote, Reservation, ReservationSource, RestrictionIssue } from '@/api/types';
import { useAuth, useHotel } from '@/auth/AuthProvider';
import { SubmitButton } from '@/components/ui';
import { addDays, daysBetween } from '@/lib/dates';
import { errorMessage, fieldMessage, notifySuccess } from '@/lib/errors';
import { formatDate, formatMoney } from '@/lib/format';
import { pickLocalized } from '@/lib/localized';
import { issueLabel, usePricingLookups } from '@/modules/pricing/shared';
import { EMPTY_GUEST, type GuestChoice, GuestPicker } from './GuestPicker';
import { newIdempotencyKey, SOURCES, useHotelToday, useInventory } from './shared';

export interface ReservationDraft {
  arrival?: string;
  departure?: string;
  room_type_id?: string;
  room_id?: string;
}

interface Line {
  key: string;
  room_type_id: string | null;
  room_id: string | null;
  rate_plan_id: string | null;
  adults: number;
  children: number;
}

export function NewReservationDrawer({
  opened,
  onClose,
  draft,
  onCreated,
}: {
  opened: boolean;
  onClose: () => void;
  draft?: ReservationDraft;
  onCreated?: (r: Reservation) => void;
}) {
  const { t } = useTranslation();
  return (
    <Drawer opened={opened} onClose={onClose} title={<Title order={3}>{t('reservations.new')}</Title>} size={1080} padding="lg">
      {opened && <ReservationForm draft={draft} onDone={(r) => (onCreated ? onCreated(r) : onClose())} onCancel={onClose} />}
    </Drawer>
  );
}

function ReservationForm({ draft, onDone, onCancel }: { draft?: ReservationDraft; onDone: (r: Reservation) => void; onCancel: () => void }) {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const { can } = useAuth();
  const qc = useQueryClient();
  const inv = useInventory();
  const today = useHotelToday();
  const idempotencyKey = useRef(newIdempotencyKey());

  const [dates, setDates] = useState<[string | null, string | null]>([draft?.arrival ?? today, draft?.departure ?? addDays(draft?.arrival ?? today, 1)]);
  const [guest, setGuest] = useState<GuestChoice>({ mode: 'new', data: EMPTY_GUEST });
  const [lines, setLines] = useState<Line[]>([
    { key: 'l0', room_type_id: draft?.room_type_id ?? null, room_id: draft?.room_id ?? null, rate_plan_id: null, adults: 2, children: 0 },
  ]);
  const [source, setSource] = useState<ReservationSource>('direct');
  const [status, setStatus] = useState<'confirmed' | 'pending'>('confirmed');
  const [externalRef, setExternalRef] = useState('');
  const [requests, setRequests] = useState('');
  const [notes, setNotes] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [override, setOverride] = useState(false);

  const [arrival, departure] = dates;
  const validDates = !!arrival && !!departure && departure > arrival;
  const nights = validDates ? daysBetween(arrival!, departure!) : 0;

  const availability = useHotelQuery<Availability[]>('calendar', '/availability', { start: arrival, end: departure }, validDates);
  const minAvailable = useMemo(() => {
    const out = new Map<string, number>();
    for (const a of availability.data ?? []) out.set(a.room_type_id, Math.min(...a.nights.map((n) => n.available)));
    return out;
  }, [availability.data]);

  // Live price quote (debounced; keeps the previous figures while recalculating).
  const quotePayload = useMemo(
    () =>
      validDates && lines.every((l) => l.room_type_id)
        ? { arrival, departure, rooms: lines.map((l) => ({ room_type_id: l.room_type_id, room_id: l.room_id || null, rate_plan_id: l.rate_plan_id, adults: l.adults, children: l.children })) }
        : null,
    [validDates, arrival, departure, lines],
  );
  const [debouncedPayload] = useDebouncedValue(quotePayload, 300);
  const quote = useQuery({
    queryKey: hotelKey(hotel.id, 'calendar', 'quote', debouncedPayload),
    queryFn: () => api.post<Quote>(`/hotels/${hotel.id}/reservations/quote`, debouncedPayload),
    enabled: !!debouncedPayload,
    placeholderData: keepPreviousData,
    retry: false,
  });

  const updateLine = (key: string, patch: Partial<Line>) => setLines((ls) => ls.map((l) => (l.key === key ? { ...l, ...patch } : l)));

  const body = (allowOverbooking: boolean) => ({
    arrival,
    departure,
    ...(guest.mode === 'existing'
      ? { guest_id: guest.guest?.id ?? null }
      : {
          guest: {
            first_name: guest.data.first_name.trim(),
            last_name: guest.data.last_name.trim(),
            email: guest.data.email.trim() || null,
            phone: guest.data.phone.trim() || null,
            nationality: guest.data.nationality,
            preferred_language: guest.data.preferred_language,
          },
        }),
    rooms: lines.map((l) => ({ room_type_id: l.room_type_id, room_id: l.room_id || null, rate_plan_id: l.rate_plan_id, adults: l.adults, children: l.children })),
    status,
    source,
    external_ref: externalRef.trim() || null,
    special_requests: requests.trim() || null,
    internal_notes: notes.trim() || null,
    allow_overbooking: allowOverbooking,
    override_restrictions: override,
  });

  const submit = async (allowOverbooking = false) => {
    setBusy(true);
    setErrors({});
    setFormError(null);
    try {
      const res = await api.post<Reservation>(`/hotels/${hotel.id}/reservations`, body(allowOverbooking), { 'Idempotency-Key': idempotencyKey.current });
      for (const e of ['reservation', 'calendar', 'guest']) void qc.invalidateQueries({ queryKey: hotelKey(hotel.id, e) });
      notifySuccess(t('reservations.created', { code: res.code }));
      onDone(res);
    } catch (err) {
      if (err instanceof ApiError && err.code === 'NO_AVAILABILITY' && can('reservations.overbook') && !allowOverbooking) {
        const night = String(err.params.night ?? '');
        modals.openConfirmModal({
          title: t('reservations.form.overbook_title'),
          children: <Text size="sm">{t('reservations.form.overbook_body', { night: formatDate(night, i18n.language) })}</Text>,
          labels: { confirm: t('reservations.form.overbook_confirm'), cancel: t('common.cancel') },
          confirmProps: { color: 'red' },
          onConfirm: () => {
            idempotencyKey.current = newIdempotencyKey();
            void submit(true);
          },
        });
      } else if (err instanceof ApiError && err.fields.length) {
        const map: Record<string, string> = {};
        for (const f of err.fields) map[f.loc.slice(1).join('.')] = fieldMessage(f.code, f.ctx);
        setErrors(map);
        setFormError(errorMessage(err));
      } else {
        setFormError(errorMessage(err));
      }
    } finally {
      setBusy(false);
    }
  };

  const guestReady = guest.mode === 'existing' ? !!guest.guest : !!(guest.data.first_name.trim() && guest.data.last_name.trim());
  const issues: RestrictionIssue[][] = lines.map((_, i) => (quote.data && !quote.isPlaceholderData ? (quote.data.stays[i]?.issues ?? []) : []));
  const restricted = issues.some((x) => x.length > 0);
  const canOverride = can('reservations.override_restrictions');
  const canSubmit = validDates && guestReady && lines.every((l) => l.room_type_id) && (!restricted || (canOverride && override));
  const typeOptions = inv.types
    .filter((rt) => rt.is_active)
    .map((rt) => {
      const free = minAvailable.get(rt.id);
      return {
        value: rt.id,
        label: `${pickLocalized(rt.name, i18n.language, hotel.default_language)}${free !== undefined ? ` · ${t('reservations.form.available_n', { count: free })}` : ''}`,
      };
    });

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <Grid gutter="xl">
        <Grid.Col span={{ base: 12, md: 7 }}>
          <Stack gap="lg">
            {formError && (
              <Alert color="red" variant="light">
                {formError}
              </Alert>
            )}
            <div>
              <DatePickerInput
                type="range"
                label={t('reservations.form.dates')}
                description={nights ? t('reservations.nights', { count: nights }) : undefined}
                value={dates}
                onChange={(v) => setDates([v[0], v[1]])}
                allowSingleDateInRange={false}
                numberOfColumns={2}
                required
                error={errors.arrival || errors.departure}
                valueFormat="ddd D MMM YYYY"
              />
            </div>

            <div>
              <Text fw={600} size="sm" mb={6}>
                {t('reservations.form.guest')}
              </Text>
              <GuestPicker value={guest} onChange={setGuest} errors={errors} />
            </div>

            <div>
              <Text fw={600} size="sm" mb={6}>
                {t('reservations.form.rooms')}
              </Text>
              <Stack gap="sm">
                {lines.map((line, i) => (
                  <RoomLineEditor
                    key={line.key}
                    line={line}
                    index={i}
                    start={validDates ? arrival : null}
                    end={validDates ? departure : null}
                    typeOptions={typeOptions}
                    minAvailable={line.room_type_id ? minAvailable.get(line.room_type_id) : undefined}
                    issues={issues[i]}
                    errors={errors}
                    onChange={(patch) => updateLine(line.key, patch)}
                    onRemove={lines.length > 1 ? () => setLines((ls) => ls.filter((l) => l.key !== line.key)) : undefined}
                  />
                ))}
                <Group>
                  <Button
                    variant="light"
                    size="xs"
                    leftSection={<IconPlus size={14} />}
                    onClick={() => setLines((ls) => [...ls, { key: `l${Date.now()}`, room_type_id: null, room_id: null, rate_plan_id: null, adults: 2, children: 0 }])}
                  >
                    {t('reservations.form.add_room')}
                  </Button>
                </Group>
              </Stack>
            </div>

            <SimpleGrid cols={{ base: 1, sm: 3 }}>
              <Select
                label={t('reservations.source')}
                allowDeselect={false}
                data={SOURCES.map((s) => ({ value: s, label: t(`reservations.sources.${s}`) }))}
                value={source}
                onChange={(v) => v && setSource(v as ReservationSource)}
              />
              <Select
                label={t('common.status')}
                allowDeselect={false}
                data={[
                  { value: 'confirmed', label: t('reservations.status.confirmed') },
                  { value: 'pending', label: t('reservations.status.pending') },
                ]}
                value={status}
                onChange={(v) => v && setStatus(v as 'confirmed' | 'pending')}
              />
              <TextInput label={t('reservations.external_ref')} value={externalRef} onChange={(e) => setExternalRef(e.currentTarget.value)} />
            </SimpleGrid>
            <Textarea label={t('reservations.special_requests')} description={t('reservations.special_requests_hint')} autosize minRows={2} value={requests} onChange={(e) => setRequests(e.currentTarget.value)} />
            <Textarea label={t('reservations.internal_notes')} description={t('reservations.internal_notes_hint')} autosize minRows={2} value={notes} onChange={(e) => setNotes(e.currentTarget.value)} />
          </Stack>
        </Grid.Col>

        <Grid.Col span={{ base: 12, md: 5 }}>
          <Card pos="sticky" top={0} bg="var(--mantine-color-default-hover)">
            <Title order={4} mb="sm">
              {t('reservations.form.summary')}
            </Title>
            {!quote.data ? (
              <Text size="sm" c="dimmed">
                {t('reservations.form.summary_hint')}
              </Text>
            ) : (
              <Stack gap={6} style={{ opacity: quote.isFetching ? 0.6 : 1 }}>
                {quote.data.rooms.map((roomNights, i) => {
                  const total = roomNights.reduce((s, n) => s + Number(n.price), 0);
                  return (
                    <Group key={i} justify="space-between" wrap="nowrap">
                      <Text size="sm">
                        {inv.typeName(lines[i]?.room_type_id)} · {t('reservations.nights', { count: roomNights.length })}
                      </Text>
                      <Text size="sm" className="hms-num">
                        {formatMoney(total, quote.data!.currency, i18n.language)}
                      </Text>
                    </Group>
                  );
                })}
                <Divider my={4} />
                {quote.data.taxes.map((tax) => (
                  <Group key={tax.code} justify="space-between" wrap="nowrap">
                    <Text size="sm" c="dimmed">
                      {pickLocalized(tax.name, i18n.language, hotel.default_language)}
                      {tax.is_inclusive ? ` (${t('settings.taxes.included')})` : ''}
                    </Text>
                    <Text size="sm" c="dimmed" className="hms-num">
                      {formatMoney(tax.amount, quote.data!.currency, i18n.language)}
                    </Text>
                  </Group>
                ))}
                <Group justify="space-between" mt={4}>
                  <Text fw={700}>{t('reservations.total')}</Text>
                  <Text fw={700} size="lg" className="hms-num">
                    {formatMoney(quote.data.grand_total, quote.data.currency, i18n.language)}
                  </Text>
                </Group>
              </Stack>
            )}
            {quote.error && (
              <Text size="xs" c="red" mt="xs">
                {errorMessage(quote.error)}
              </Text>
            )}
            {restricted && (
              <Alert color="yellow" variant="light" mt="md" icon={<IconAlertTriangle size={16} />} title={t('reservations.form.restricted_title')}>
                {canOverride ? (
                  <Checkbox label={t('reservations.form.override_restrictions')} checked={override} onChange={(e) => setOverride(e.currentTarget.checked)} />
                ) : (
                  <Text size="sm">{t('reservations.form.restricted_body')}</Text>
                )}
              </Alert>
            )}
            <Stack mt="lg" gap="xs">
              <SubmitButton size="md" fullWidth loading={busy} disabled={!canSubmit}>
                {status === 'pending' ? t('reservations.form.create_pending') : t('reservations.form.create')}
              </SubmitButton>
              <Button variant="default" fullWidth onClick={onCancel}>
                {t('common.cancel')}
              </Button>
            </Stack>
          </Card>
        </Grid.Col>
      </Grid>
    </form>
  );
}

function RoomLineEditor({
  line,
  index,
  start,
  end,
  typeOptions,
  minAvailable,
  issues,
  errors,
  onChange,
  onRemove,
}: {
  line: Line;
  index: number;
  start: string | null;
  end: string | null;
  typeOptions: { value: string; label: string }[];
  minAvailable: number | undefined;
  issues: RestrictionIssue[];
  errors: Record<string, string>;
  onChange: (patch: Partial<Line>) => void;
  onRemove?: () => void;
}) {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const inv = useInventory();
  const pricing = usePricingLookups();
  const rt = line.room_type_id ? inv.typeById.get(line.room_type_id) : undefined;
  const offers = useHotelQuery<Offer[]>(
    'rate',
    '/rates/offers',
    { arrival: start, departure: end, adults: line.adults, children: line.children, room_type_id: line.room_type_id },
    !!start && !!end && !!line.room_type_id,
  );
  const rateOptions = (offers.data ?? []).map((o) => ({
    value: o.rate_plan_id,
    label: `${pricing.planName(o.rate_plan_id)} · ${formatMoney(o.total, hotel.currency_code, i18n.language)}${o.bookable ? '' : ' ⚠'}`,
  }));
  const free = useHotelQuery<AvailableRoom[]>(
    'calendar',
    '/available-rooms',
    { start, end, room_type_id: line.room_type_id },
    !!start && !!end && !!line.room_type_id,
  );
  const roomOptions = [
    { value: '', label: t('reservations.form.assign_later') },
    ...(free.data ?? []).map((r) => ({ value: r.id, label: r.name ? `${r.number} · ${r.name}` : r.number })),
  ];
  const err = (f: string) => errors[`rooms.${index}.${f}`];

  return (
    <Card padding="sm" withBorder>
      <Grid gutter="xs" align="flex-end">
        <Grid.Col span={{ base: 12, sm: 5 }}>
          <Select
            label={t('rooms.category')}
            required
            allowDeselect={false}
            data={typeOptions}
            value={line.room_type_id}
            onChange={(v) => onChange({ room_type_id: v, room_id: null })}
            error={err('room_type_id')}
          />
        </Grid.Col>
        <Grid.Col span={{ base: 12, sm: 3 }}>
          <Select label={t('rooms.number')} data={roomOptions} value={line.room_id ?? ''} onChange={(v) => onChange({ room_id: v || null })} disabled={!line.room_type_id || !start} />
        </Grid.Col>
        <Grid.Col span={{ base: 5, sm: 2 }}>
          <NumberInput label={t('reservations.adults')} min={1} max={rt?.max_adults ?? 50} value={line.adults} onChange={(v) => onChange({ adults: Number(v) || 1 })} error={err('adults')} />
        </Grid.Col>
        <Grid.Col span={{ base: 5, sm: 'auto' }}>
          <NumberInput label={t('reservations.children')} min={0} max={rt?.max_children ?? 50} value={line.children} onChange={(v) => onChange({ children: Number(v) || 0 })} error={err('children')} />
        </Grid.Col>
        {onRemove && (
          <Grid.Col span="content">
            <ActionIcon variant="subtle" color="red" size="lg" mb={4} aria-label={t('common.remove')} onClick={onRemove}>
              <IconTrash size={16} />
            </ActionIcon>
          </Grid.Col>
        )}
      </Grid>
      <Select
        mt="xs"
        label={t('reservations.rate')}
        data={rateOptions}
        value={line.rate_plan_id ?? pricing.defaultPlan?.id ?? null}
        onChange={(v) => onChange({ rate_plan_id: v })}
        allowDeselect={false}
        disabled={!line.room_type_id || !start}
      />
      {issues.length > 0 && (
        <Text size="xs" c="orange.8" mt={4}>
          {issues.map((x) => issueLabel(x, t, i18n.language)).join(' · ')}
        </Text>
      )}
      {minAvailable !== undefined && minAvailable <= 0 && (
        <Badge color="red" variant="light" mt="xs" radius="sm">
          {t('reservations.form.sold_out')}
        </Badge>
      )}
    </Card>
  );
}
